"""Decorator-friendly actions and bounded delivery shared by MAVLink scopes."""

from __future__ import annotations

import asyncio
import inspect
import threading
from itertools import count
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..events.callback import CallbackSubscription


@dataclass(frozen=True, slots=True)
class MavlinkAction:
    source: Any
    vehicle: Any = None
    component: Any = None
    error: Exception | None = None


class AsyncDelivery:
    """One bounded callback queue and one consumer per async runtime.

    Overflow drops the oldest queued callback and increments ``dropped``.
    Running callbacks are cancelled and awaited during shutdown.
    """

    def __init__(
        self,
        capacity: int = 1024,
        action_capacity: int = 1024,
        concurrency: int = 1,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("Async delivery capacity must be a positive integer")
        self.capacity = capacity
        if isinstance(action_capacity, bool) or not isinstance(action_capacity, int) or action_capacity <= 0:
            raise ValueError("Action delivery capacity must be a positive integer")
        self.action_capacity = action_capacity
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency <= 0:
            raise ValueError("Async delivery concurrency must be a positive integer")
        self.concurrency = concurrency
        self.failure: Exception | None = None
        self.on_failure = None
        self._fault_pending = False
        self.dropped = 0
        self._queue: deque[tuple[Callable, Any]] = deque()
        self._actions: deque[tuple[Callable, Any]] = deque()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._scheduled = False

    def raise_if_failed(self) -> None:
        if self.failure is not None:
            raise RuntimeError("Async MAVLink delivery failed; stop before restarting") from self.failure

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._loop is not None:
                if self.failure is not None:
                    raise RuntimeError("Stop the failed delivery before restarting") from self.failure
                if self._loop is not loop:
                    raise RuntimeError("Runtime belongs to another event loop")
                return
            if self._task is not None and not self._task.done():
                raise RuntimeError("Previous async delivery consumer has not stopped")
            self._loop = loop
            self._ready = asyncio.Event()
            self._queue.clear()
            self._actions.clear()
            self.failure = None
            self._fault_pending = False
            self._scheduled = False
            self._task = loop.create_task(self._consume())

    def submit(self, callback: Callable, event: Any, *, action: bool = False) -> None:
        with self._lock:
            if self._loop is None:
                return
            if self.failure is not None:
                return
            if action:
                if len(self._actions) == self.action_capacity:
                    self._fail_locked(
                        BufferError("MAVLink lifecycle delivery capacity exceeded")
                    )
                else:
                    self._actions.append((callback, event))
            else:
                if len(self._queue) == self.capacity:
                    self._queue.popleft()
                    self.dropped += 1
                self._queue.append((callback, event))
            if not self._scheduled:
                self._scheduled = True
                try:
                    self._loop.call_soon_threadsafe(self._ready.set)
                except RuntimeError:
                    self._queue.clear()
                    self._actions.clear()
                    self._fail_locked(RuntimeError("MAVLink delivery loop is closed"))
                    self._scheduled = False

    def _fail_locked(self, error: Exception) -> None:
        if self.failure is None:
            self.failure = error
            self._fault_pending = True

    def _fail(self, error: Exception) -> None:
        with self._lock:
            self._fail_locked(error)
            ready = self._ready
            if ready is not None and not self._scheduled:
                self._scheduled = True
                ready.set()

    async def _consume(self) -> None:
        while True:
            await self._ready.wait()
            with self._lock:
                actions = tuple(self._actions)
                callbacks = tuple(self._queue)
                fault = self.failure if self._fault_pending else None
                self._fault_pending = False
                self._actions.clear()
                self._queue.clear()
                self._scheduled = False
                self._ready.clear()
            if fault is not None and self.on_failure is not None:
                await self.on_failure(fault)
            for callback, event in actions:
                if self._loop is None:
                    return
                try:
                    await callback(event)
                except asyncio.CancelledError:
                    if self._loop is None:
                        raise
                except Exception as exc:
                    self._fail(exc)
                    break
            if self.failure is not None:
                continue
            if self.concurrency == 1:
                groups = tuple((item,) for item in callbacks)
            else:
                groups = tuple(
                    callbacks[index:index + self.concurrency]
                    for index in range(0, len(callbacks), self.concurrency)
                )
            for group in groups:
                results = await asyncio.gather(
                    *(callback(event) for callback, event in group),
                    return_exceptions=True,
                )
                error = next(
                    (result for result in results if isinstance(result, Exception)),
                    None,
                )
                if error is not None:
                    self._fail(error)
                    break
            if self._loop is None:
                return

    async def stop(self) -> None:
        with self._lock:
            task = self._task
            self._loop = None
            self._queue.clear()
            self._actions.clear()
            self._scheduled = False
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=2.0)
            if not done:
                raise TimeoutError("Async callback did not stop after cancellation")
            if not task.cancelled():
                task.result()
            self._task = None


class MavlinkActions:
    """Common subscription syntax; callbacks never run under the registry lock."""

    action_names = frozenset({"connected", "disconnected", "error"})

    def __init__(self, delivery: AsyncDelivery | None = None) -> None:
        self._delivery = delivery
        self._topics: dict[str, dict[int, tuple]] = {}
        self._ids = count(1)
        self._topics_lock = threading.RLock()
        self._actions_closed = False
        self._worker = None

    def _register(self, topic: str, callback=None, *, once: bool = False, **options):
        if callback is None:
            def decorate(function):
                return self._register(topic, function, once=once, **options)
            return decorate
        asynchronous = inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
            getattr(callback, "__call__", None)
        )
        if asynchronous != (self._delivery is not None):
            raise TypeError("Callback must match the runtime's sync/async mode")
        if not callable(callback):
            raise TypeError("Callback must be callable")
        with self._topics_lock:
            if self._actions_closed:
                raise RuntimeError("MAVLink scope is closed")
            identifier = next(self._ids)

            def cancel():
                with self._topics_lock:
                    entries = self._topics.get(topic)
                    if entries is not None:
                        entries.pop(identifier, None)
                        if not entries:
                            self._topics.pop(topic, None)

            subscription = CallbackSubscription(identifier, cancel, callback,
                asynchronous=self._delivery is not None, once=once, **options)
            self._topics.setdefault(topic, {})[identifier] = (subscription, callback, False)
            return subscription

    def _claim(self, subscription, once):
        with self._topics_lock:
            if self._actions_closed or not subscription.active:
                return False
            if once:
                subscription.cancel()
            return True

    async def _deliver_async(self, topic, entry, event):
        subscription, callback, once = entry
        if self._claim(subscription, once):
            try:
                await subscription.invoke_async(event)
            except asyncio.CancelledError:
                if (self._delivery is None or self._delivery._loop is None
                        or asyncio.current_task() is not self._delivery._task):
                    raise
                if topic != "action:error":
                    await self._emit_async("action:error", MavlinkAction(
                        self, error=RuntimeError("MAVLink callback was cancelled"),
                    ))
            except Exception as exc:
                if topic != "action:error":
                    await self._emit_async("action:error", MavlinkAction(self, error=exc))

    async def _emit_async(self, topic, event):
        with self._topics_lock:
            entries = tuple(self._topics.get(topic, {}).values())
        for entry in entries:
            await self._deliver_async(topic, entry, event)

    def on(self, name: str, callback=None, *, once: bool = False, **options):
        if name not in self.action_names:
            raise ValueError(f"Unsupported MAVLink action: {name}")
        return self._register(f"action:{name}", callback, once=once, **options)

    def on_connected(self, callback=None, *, once=False, **options):
        return self.on("connected", callback, once=once, **options)

    def on_disconnected(self, callback=None, *, once=False, **options):
        return self.on("disconnected", callback, once=once, **options)

    def on_error(self, callback=None, *, once=False, **options):
        return self.on("error", callback, once=once, **options)

    def subscribe(self, message_type: str, callback=None, *, once=False, **options):
        normalized = message_type.strip().upper()
        if not normalized:
            raise ValueError("Message type must not be empty")
        return self._register(f"message:{normalized}", callback, once=once, **options)

    def _emit(self, topic: str, event: Any) -> None:
        if self._delivery is None and topic in {"action:start", "action:stop", "action:removed"}:
            self._emit_sync(topic, event)
            return
        if self._delivery is None and self._worker is not None:
            entries = None
            if not topic.startswith("action:"):
                with self._topics_lock:
                    entries = tuple(self._topics.get(topic, {}).values())
                    if not entries:
                        return
            self._worker.submit(lambda value: self._emit_sync(topic, value, entries=entries), event,
                                action=topic.startswith("action:"))
            return
        if self._delivery is not None and topic.startswith("action:"):
            # Resolve handlers when the ordered action is delivered, so an
            # on_added callback can install the following on_connected hooks.
            async def deliver_action(event):
                await self._emit_async(topic, event)
            self._delivery.submit(deliver_action, event, action=True)
            return
        with self._topics_lock:
            entries = tuple(self._topics.get(topic, {}).values())
        for entry in entries:
            if self._delivery is not None:
                async def deliver(event, entry=entry):
                    await self._deliver_async(topic, entry, event)
                self._delivery.submit(deliver, event)
            else:
                subscription, callback, once = entry
                if self._claim(subscription, once):
                    try:
                        result = subscription.invoke(event)
                        if inspect.isawaitable(result):
                            if inspect.iscoroutine(result):
                                result.close()
                            raise TypeError("Sync callback returned an awaitable")
                    except Exception as exc:
                        if topic != "action:error":
                            self._emit("action:error", MavlinkAction(self, error=exc))

    def _emit_sync(self, topic: str, event: Any, *, entries=None) -> None:
        if entries is None:
            with self._topics_lock:
                entries = tuple(self._topics.get(topic, {}).values())
        for subscription, callback, once in entries:
            if not self._claim(subscription, once):
                continue
            try:
                subscription.invoke(event)
            except asyncio.CancelledError:
                if topic != "action:error":
                    self._emit_sync("action:error", MavlinkAction(self, error=RuntimeError("Callback was cancelled")))
            except Exception as exc:
                if topic != "action:error":
                    self._emit_sync("action:error", MavlinkAction(self, error=exc))

    def _close_actions(self) -> None:
        with self._topics_lock:
            self._actions_closed = True
            subscriptions = tuple(entry[0] for entries in self._topics.values()
                                  for entry in entries.values())
            self._topics.clear()
        for subscription in subscriptions:
            subscription.cancel()
