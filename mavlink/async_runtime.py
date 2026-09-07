"""Async runtime using the same transport and discovered endpoint machinery."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from itertools import count

from ..events import AsyncEventBus, Subscription

from .actions import AsyncDelivery, MavlinkAction
from .runtime import MavlinkRuntime
from .history import MessageHistory


class AsyncMavlinkRuntime:
    """Own a receive thread and a bounded callback consumer on the caller's loop."""

    def __init__(self, endpoint=None, *, delivery_capacity=1024, action_capacity=1024, **options):
        self._delivery = AsyncDelivery(delivery_capacity, action_capacity)
        self._runtime = MavlinkRuntime(endpoint, _delivery=self._delivery, **options)
        self._delivery.on_failure = self._report_delivery_failure
        self.vehicles = self._runtime.vehicles
        self._lifecycle_lock = asyncio.Lock()
        self._closing = False
        self._close_task = None
        self._raw_ids = count(1)
        self._raw_subscriptions = []
        self._messages = AsyncEventBus()
        self._packets = AsyncEventBus()
        self._errors = AsyncEventBus()
        for source, destination in (
            (self._runtime.messages, self._messages),
            (self._runtime.errors, self._errors),
            (self._runtime.peer.packets if self._runtime.peer else None, self._packets),
        ):
            if source is not None:
                self._raw_subscriptions.append(source.subscribe(
                    lambda event, destination=destination: self._delivery.submit(
                        destination.publish, event, action=destination is self._errors,
                    ) if destination.subscriber_count else None,
                ))

    @property
    def state(self):
        return replace(self._runtime.state, running=self.running)

    async def _report_delivery_failure(self, error):
        self._runtime._registry.fail_waiters()
        await self._runtime._emit_async("action:error", MavlinkAction(self, error=error))

    @property
    def running(self):
        return self._runtime.running and self._delivery.failure is None

    @property
    def delivery_error(self):
        return self._delivery.failure

    @property
    def dropped_callbacks(self):
        return self._delivery.dropped

    def on(self, name, callback=None, *, once=False, **options):
        return self._runtime.on(name, callback, once=once, **options)

    def on_start(self, callback=None, *, once=False, **options):
        return self.on("start", callback, once=once, **options)

    def on_stop(self, callback=None, *, once=False, **options):
        return self.on("stop", callback, once=once, **options)

    def on_error(self, callback=None, *, once=False, **options):
        return self.on("error", callback, once=once, **options)

    def handle(self, packet_type, handler=None, *, replace=False):
        return self._runtime.handle(packet_type, handler, replace=replace)

    def add_history(self, history: MessageHistory) -> Subscription:
        return self._runtime.add_history(history)

    async def notify(self, packet_type, payload=None):
        self._delivery.raise_if_failed()
        return await asyncio.to_thread(self._runtime.notify, packet_type, payload)

    async def request(self, packet_type, payload=None, **options):
        self._delivery.raise_if_failed()
        return await asyncio.to_thread(self._runtime.request, packet_type, payload, **options)

    async def send(self, message):
        self._delivery.raise_if_failed()
        return await asyncio.to_thread(self._runtime.send, message)

    async def send_named(self, message_name, **parameters):
        self._delivery.raise_if_failed()
        return await asyncio.to_thread(self._runtime.send_named, message_name, **parameters)

    def latest(self, message_filter=None):
        return self._runtime.latest(message_filter)

    @property
    def application_enabled(self):
        return self._runtime.application_enabled

    @property
    def client(self):
        return self._runtime.client

    @property
    def connection(self):
        return self._runtime.connection

    @property
    def router(self):
        return self._runtime.router

    @property
    def messages(self):
        return self._messages

    @property
    def packets(self):
        if not self.application_enabled:
            raise RuntimeError("MAVLink application channel is not configured")
        return self._packets

    @property
    def errors(self):
        return self._errors

    def subscribe(self, message_types, callback=None, *, predicate=None, once=False, **options):
        if callback is None:
            def decorate(function):
                return self.subscribe(message_types, function, predicate=predicate, once=once, **options)
            return decorate
        if not (inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
                getattr(callback, "__call__", None))):
            raise TypeError("Async runtime requires an async callback")
        topic = f"raw:{next(self._raw_ids)}"
        from .filter import MavlinkMessageFilter
        message_filter = message_types if isinstance(message_types, MavlinkMessageFilter) else MavlinkMessageFilter(message_types=message_types)
        if isinstance(message_types, MavlinkMessageFilter) and predicate is not None:
            raise ValueError("Use a MavlinkMessageFilter or predicate, not both")
        logical = self._runtime._register(topic, callback, once=once,
            predicate=predicate or message_filter.predicate, **options)
        message_filter = replace(message_filter, predicate=None)
        try:
            source = self.client.subscribe(lambda message: self._runtime._emit(topic, message), message_filter)
        except BaseException:
            logical.cancel()
            raise
        original_cancel = logical._cancel
        def cancel():
            original_cancel()
            source.cancel()
            if logical in self._raw_subscriptions:
                self._raw_subscriptions.remove(logical)
        logical._cancel = cancel
        self._raw_subscriptions.append(logical)
        if not logical.active:
            cancel()
        return logical

    def once(self, message_types, callback=None, *, predicate=None, **options):
        return self.subscribe(message_types, callback, predicate=predicate, once=True, **options)

    async def wait_for(self, message_types, *, predicate=None, timeout=3.0, after_sequence=None):
        self._delivery.raise_if_failed()
        result = await asyncio.to_thread(
            self._runtime.wait_for, message_types, predicate=predicate,
            timeout=timeout, after_sequence=after_sequence,
        )
        self._delivery.raise_if_failed()
        return result

    async def _finish_io(self, operation):
        task = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A cancelled await does not stop blocking transport I/O. Join it
            # before allowing another lifecycle operation to touch the socket.
            await task
            raise

    async def start(self):
        async with self._lifecycle_lock:
            if self._closing:
                raise RuntimeError("MAVLink runtime is closing")
            was_running = self.running
            if not was_running and self._runtime._application_handlers._tasks:
                raise RuntimeError("Previous application handlers have not stopped")
            self._delivery.start()
            try:
                await self._finish_io(self._runtime.start)
            except BaseException:
                try:
                    await self._finish_io(self._runtime.stop)
                finally:
                    await self._delivery.stop()
                raise
        if not was_running:
            try:
                await self._runtime._emit_async("action:start", MavlinkAction(self))
            except BaseException:
                await self.stop()
                raise

    async def stop(self):
        async with self._lifecycle_lock:
            was_running = self.running
            try:
                await self._finish_io(self._runtime.stop)
            finally:
                try:
                    await self._delivery.stop()
                finally:
                    await self._runtime._application_handlers.finish_async()
        if was_running:
            await self._runtime._emit_async("action:stop", MavlinkAction(self))

    async def close(self):
        current = asyncio.current_task()
        if self._close_task is not None and not self._close_task.done():
            if current is self._close_task or current is self._delivery._task:
                return
            await asyncio.shield(self._close_task)
            return
        self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        self._closing = True
        try:
            await self.stop()
            async with self._lifecycle_lock:
                try:
                    await self._finish_io(self._runtime.close)
                finally:
                    await self._delivery.stop()
            for subscription in tuple(self._raw_subscriptions):
                subscription.cancel()
            self._raw_subscriptions.clear()
            await self._messages.close()
            await self._packets.close()
            await self._errors.close()
        finally:
            self._closing = False

    async def reconnect(self):
        await self.stop()
        await self.start()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_args):
        await self.close()
