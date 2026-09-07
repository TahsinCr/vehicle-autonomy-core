"""Source-scoped application handlers using the shared bounded dispatcher."""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any

from ..events import Subscription
from .dispatch import MavlinkApplicationResult


class ApplicationHandlers:
    """One dispatcher route per packet type; component overrides vehicle/global."""

    def __init__(self, runtime):
        self.runtime = runtime
        self._lock = threading.RLock()
        self._entries: dict[tuple, tuple] = {}
        self._routes: dict[str, Subscription] = {}
        self._futures: set[Any] = set()
        self._tasks: set[asyncio.Task] = set()
        self._running = False

    def start(self):
        with self._lock:
            self._running = True

    def register(self, packet_type, handler=None, *, scope=None, replace=False):
        if handler is None:
            def decorate(function):
                self.register(packet_type, function, scope=scope, replace=replace)
                return function
            return decorate
        asynchronous = inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(
            getattr(handler, "__call__", None)
        )
        if not callable(handler) or asynchronous != (self.runtime._delivery is not None):
            raise TypeError("Application handler must match the runtime's sync/async mode")
        normalized = str(packet_type).strip().lower()
        dispatcher = self.runtime.dispatcher
        if dispatcher is None:
            raise RuntimeError("MAVLink application dispatcher is not configured")
        if not normalized:
            raise ValueError("Application packet type must not be empty")
        key = (None, None, normalized) if scope is None else (
            scope.system_id, None if scope.vehicle is scope else scope.component_id, normalized,
        )
        token = object()
        with self._lock:
            if self.runtime._closed or (scope is not None and scope._actions_closed):
                raise RuntimeError("MAVLink scope is closed")
            if key in self._entries and not replace:
                raise ValueError(f"Application handler already registered: {normalized}")
            if normalized not in self._routes:
                self._routes[normalized] = dispatcher.register(normalized, self.dispatch)

            def cancel():
                with self._lock:
                    entry = self._entries.get(key)
                    if entry is not None and entry[0] is token:
                        self._entries.pop(key)
                        if not any(item[2] == normalized for item in self._entries):
                            self._routes.pop(normalized).cancel()

            subscription = Subscription(id(token), cancel)
            previous = self._entries.get(key)
            self._entries[key] = (token, handler, scope, subscription)
            if previous is not None:
                previous[3].cancel()
            return subscription

    def dispatch(self, packet):
        packet_type = packet.packet_type.strip().lower()
        with self._lock:
            if not self._running:
                raise RuntimeError("Application handlers are stopped")
            entry = next((self._entries[key] for key in (
                (packet.source_system, packet.source_component, packet_type),
                (packet.source_system, None, packet_type),
                (None, None, packet_type),
            ) if key in self._entries), None)
            if entry is None:
                return MavlinkApplicationResult.failure("No handler for this source")
            _, handler, scope, _ = entry
            if scope is not None and scope._actions_closed:
                raise RuntimeError("Application handler scope is closed")
            delivery = self.runtime._delivery
            if delivery is None:
                future = None
            else:
                loop = delivery._loop
                if loop is None or loop.is_closed():
                    raise RuntimeError("Async application runtime is stopped")
                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_loop = None
                if current_loop is loop:
                    raise RuntimeError("Application dispatch must run on a dispatcher worker")

                async def invoke():
                    task = asyncio.current_task()
                    self._tasks.add(task)
                    try:
                        with self._lock:
                            if not self._running:
                                raise RuntimeError("Application handlers are stopped")
                        return await handler(packet)
                    finally:
                        self._tasks.discard(task)

                coroutine = invoke()
                try:
                    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
                except BaseException:
                    coroutine.close()
                    raise
                self._futures.add(future)
        if future is None:
            result = handler(packet)
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("Sync application handler returned an awaitable")
            return result
        try:
            return future.result()
        finally:
            with self._lock:
                self._futures.discard(future)

    def remove_scope(self, scope):
        with self._lock:
            subscriptions = tuple(entry[3] for entry in self._entries.values()
                                  if entry[2] is scope)
        for subscription in subscriptions:
            subscription.cancel()

    def stop(self):
        with self._lock:
            self._running = False
            futures = tuple(self._futures)
        for future in futures:
            future.cancel()

    async def finish_async(self):
        # run_coroutine_threadsafe cancellation is posted to the loop. Let
        # those callbacks run before inspecting the actual handler tasks.
        await asyncio.sleep(0)
        tasks = set(self._tasks)
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=2.0)
            if pending:
                raise TimeoutError("Async application handler ignored cancellation")

    def close(self):
        self.stop()
        with self._lock:
            subscriptions = tuple(entry[3] for entry in self._entries.values())
        for subscription in subscriptions:
            subscription.cancel()
