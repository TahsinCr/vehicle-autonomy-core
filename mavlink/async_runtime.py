"""Async runtime using the same transport and discovered endpoint machinery."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar, cast, overload

from ..events import AsyncEventBus, Subscription

from .actions import AsyncDelivery, MavlinkAction
from .application import MavlinkApplicationPacket
from .client import MavlinkClient
from .connection import MavlinkConnection
from .dispatch import MavlinkApplicationHandler
from .endpoint import MavlinkEndpoint
from .history import MessageHistory
from .filter import MessagePredicate, MessageTypeInput, MavlinkMessageFilter
from .peer import MavlinkApplicationResponse
from .protocols import JsonValue, MavlinkMessage
from .router import MavlinkIngressFilter, MavlinkMessageRouter
from .runtime import MavlinkRuntime, MavlinkRuntimeError, MavlinkRuntimeState


_ResultT = TypeVar("_ResultT")
AsyncMavlinkCallback = Callable[[MavlinkMessage], Awaitable[object]]


class AsyncMavlinkRuntime:
    """Own a receive thread and a bounded callback consumer on the caller's loop."""

    def __init__(
        self,
        endpoint: MavlinkEndpoint | None = None,
        *,
        delivery_capacity: int = 1024,
        action_capacity: int = 1024,
        callback_concurrency: int = 1,
        **options: object,
    ) -> None:
        self._delivery = AsyncDelivery(
            delivery_capacity,
            action_capacity,
            callback_concurrency,
        )
        self._runtime = MavlinkRuntime(endpoint, _delivery=self._delivery, **options)
        self._support = self._runtime._support
        self._support.configure_async_io(self._finish_io)
        self._delivery.on_failure = self._report_delivery_failure
        self.vehicles = self._runtime.vehicles
        self._lifecycle_lock = asyncio.Lock()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._raw_subscriptions: list[Subscription] = []
        self._messages: AsyncEventBus[MavlinkMessage] = AsyncEventBus()
        self._packets: AsyncEventBus[MavlinkApplicationPacket] = AsyncEventBus()
        self._errors: AsyncEventBus[MavlinkRuntimeError] = AsyncEventBus()
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
    def state(self) -> MavlinkRuntimeState:
        return replace(self._runtime.state, running=self.running)

    async def _report_delivery_failure(self, error: Exception) -> None:
        self._support.fail_waiters()
        await self._support.emit_error(error, self)

    @property
    def running(self) -> bool:
        return self._runtime.running and self._delivery.failure is None

    @property
    def delivery_error(self) -> Exception | None:
        return self._delivery.failure

    @property
    def dropped_callbacks(self) -> int:
        return self._delivery.dropped

    def prune_vehicles(self, *, older_than: float | None = None) -> int:
        return self._runtime.prune_vehicles(older_than=older_than)

    def on(
        self,
        name: str,
        callback: Callable[[MavlinkAction], Awaitable[object]] | None = None,
        *,
        once: bool = False,
        **options: object,
    ) -> Subscription | Callable[[Callable[[MavlinkAction], Awaitable[object]]], Subscription]:
        return cast(
            Subscription | Callable[[Callable[[MavlinkAction], Awaitable[object]]], Subscription],
            self._runtime.on(name, callback, once=once, **options),
        )

    def on_start(
        self,
        callback: Callable[[MavlinkAction], Awaitable[object]] | None = None,
        *,
        once: bool = False,
        **options: object,
    ) -> Subscription | Callable[[Callable[[MavlinkAction], Awaitable[object]]], Subscription]:
        return self.on("start", callback, once=once, **options)

    def on_stop(
        self,
        callback: Callable[[MavlinkAction], Awaitable[object]] | None = None,
        *,
        once: bool = False,
        **options: object,
    ) -> Subscription | Callable[[Callable[[MavlinkAction], Awaitable[object]]], Subscription]:
        return self.on("stop", callback, once=once, **options)

    def on_error(
        self,
        callback: Callable[[MavlinkAction], Awaitable[object]] | None = None,
        *,
        once: bool = False,
        **options: object,
    ) -> Subscription | Callable[[Callable[[MavlinkAction], Awaitable[object]]], Subscription]:
        return self.on("error", callback, once=once, **options)

    def handle(
        self,
        packet_type: str,
        handler: MavlinkApplicationHandler | None = None,
        *,
        replace: bool = False,
    ) -> Subscription:
        return self._runtime.handle(packet_type, handler, replace=replace)

    def add_history(self, history: MessageHistory) -> Subscription:
        return self._runtime.add_history(history)

    def add_filter(self, predicate: MavlinkIngressFilter) -> Subscription:
        """Register a synchronous ingress filter on the shared reader."""

        return self._runtime.add_filter(predicate)

    async def notify(
        self,
        packet_type: str,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> MavlinkApplicationPacket:
        self._delivery.raise_if_failed()
        return await self._finish_io(lambda: self._runtime.notify(packet_type, payload))

    async def request(
        self,
        packet_type: str,
        payload: Mapping[str, JsonValue] | None = None,
        **options: object,
    ) -> MavlinkApplicationResponse:
        self._delivery.raise_if_failed()
        return await self._finish_io(
            lambda: self._runtime.request(packet_type, payload, **options)
        )

    async def send(self, message: MavlinkMessage) -> None:
        self._delivery.raise_if_failed()
        return await self._finish_io(lambda: self._runtime.send(message))

    async def send_named(self, message_name: str, **parameters: object) -> None:
        self._delivery.raise_if_failed()
        return await self._finish_io(
            lambda: self._runtime.send_named(message_name, **parameters)
        )

    def latest(
        self,
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
    ) -> MavlinkMessage | None:
        return self._runtime.latest(message_filter)

    @property
    def application_enabled(self) -> bool:
        return self._runtime.application_enabled

    @property
    def client(self) -> MavlinkClient:
        return self._runtime.client

    @property
    def connection(self) -> MavlinkConnection:
        return self._runtime.connection

    @property
    def router(self) -> MavlinkMessageRouter:
        return self._runtime.router

    @property
    def messages(self) -> AsyncEventBus[MavlinkMessage]:
        return self._messages

    @property
    def packets(self) -> AsyncEventBus[MavlinkApplicationPacket]:
        if not self.application_enabled:
            raise RuntimeError("MAVLink application channel is not configured")
        return self._packets

    @property
    def errors(self) -> AsyncEventBus[MavlinkRuntimeError]:
        return self._errors

    @overload
    def subscribe(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        callback: None = None,
        *,
        predicate: MessagePredicate | None = None,
        once: bool = False,
        **options: object,
    ) -> Callable[[AsyncMavlinkCallback], Subscription]: ...

    @overload
    def subscribe(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        callback: AsyncMavlinkCallback,
        *,
        predicate: MessagePredicate | None = None,
        once: bool = False,
        **options: object,
    ) -> Subscription: ...

    def subscribe(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        callback: AsyncMavlinkCallback | None = None,
        *,
        predicate: MessagePredicate | None = None,
        once: bool = False,
        **options: object,
    ) -> Subscription | Callable[
        [AsyncMavlinkCallback], Subscription
    ]:
        if callback is None:
            def decorate(
                function: AsyncMavlinkCallback,
            ) -> Subscription:
                return self.subscribe(message_types, function, predicate=predicate, once=once, **options)
            return decorate
        logical = self._support.subscribe(
            message_types,
            callback,
            predicate=predicate,
            once=once,
            **options,
        )
        original_cancel = logical._cancel

        def cancel():
            original_cancel()
            if logical in self._raw_subscriptions:
                self._raw_subscriptions.remove(logical)

        logical._cancel = cancel
        self._raw_subscriptions.append(logical)
        if not logical.active:
            cancel()
        return logical

    def once(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        callback: AsyncMavlinkCallback | None = None,
        *,
        predicate: MessagePredicate | None = None,
        **options: object,
    ) -> Subscription | Callable[[AsyncMavlinkCallback], Subscription]:
        return self.subscribe(message_types, callback, predicate=predicate, once=True, **options)

    async def wait_for(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        *,
        predicate: MessagePredicate | None = None,
        timeout: float = 3.0,
        after_sequence: int | None = None,
    ) -> MavlinkMessage:
        self._delivery.raise_if_failed()
        result = await self._finish_io(
            lambda: self._runtime.wait_for(
                message_types,
                predicate=predicate,
                timeout=timeout,
                after_sequence=after_sequence,
            )
        )
        self._delivery.raise_if_failed()
        return result

    async def _finish_io(self, operation: Callable[[], _ResultT]) -> _ResultT:
        task = asyncio.create_task(asyncio.to_thread(operation))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Repeated cancellation must not detach blocking transport I/O.
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._closing:
                raise RuntimeError("MAVLink runtime is closing")
            was_running = self.running
            if not was_running and self._support.has_pending_handlers():
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
                await self._support.emit_action("start", self)
            except BaseException:
                await self.stop()
                raise

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            was_running = self.running
            try:
                await self._finish_io(self._runtime.stop)
            finally:
                try:
                    await self._delivery.stop()
                finally:
                    await self._support.finish_handlers()
        if was_running:
            await self._support.emit_action("stop", self)

    async def close(self) -> None:
        current = asyncio.current_task()
        if self._close_task is not None and not self._close_task.done():
            if current is self._close_task or current is self._delivery._task:
                return
            await asyncio.shield(self._close_task)
            return
        self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
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

    async def reconnect(self) -> None:
        await self.stop()
        await self.start()

    async def __aenter__(self) -> AsyncMavlinkRuntime:
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()
