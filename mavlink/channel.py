from __future__ import annotations

import asyncio
import threading
from collections import deque

from ..abstracts import Service
from ..events import Subscription
from .filter import MessageTypeInput, MavlinkMessageFilter
from .protocols import MavlinkMessage
from .router import MavlinkMessageRouter


class MavlinkAsyncChannel(Service):
    """Bounded, filtered bridge from the router thread into asyncio."""

    def __init__(
        self,
        router: MavlinkMessageRouter,
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
        *,
        maxsize: int = 128,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        if maxsize <= 0:
            raise ValueError("MAVLink async channel maxsize pozitif olmalı")
        self._router = router
        self._message_filter = message_filter
        self._queue: asyncio.Queue[MavlinkMessage] = asyncio.Queue(maxsize=maxsize)
        self._maxsize = maxsize
        self._incoming: deque[MavlinkMessage] = deque()
        self._configured_loop = loop
        self._loop = loop
        self._subscription: Subscription | None = None
        self._dropped_messages = 0
        self._bridge_lock = threading.Lock()
        self._drain_scheduled = False
        self._generation = 0
        self._queued_count = 0

    @property
    def dropped_messages(self) -> int:
        with self._bridge_lock:
            return self._dropped_messages

    @property
    def pending_messages(self) -> int:
        with self._bridge_lock:
            return self._queued_count + len(self._incoming)

    def start(self) -> None:
        if self._subscription is not None:
            return
        loop = self._loop
        if loop is not None and loop.is_closed():
            if self._configured_loop is not None:
                raise RuntimeError("MavlinkAsyncChannel event loop kapalı")
            loop = None
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError as exc:
                raise RuntimeError(
                    "MavlinkAsyncChannel.start çalışan bir asyncio loop içinde çağrılmalı"
                ) from exc
            self._loop = loop
        with self._bridge_lock:
            self._generation += 1
            generation = self._generation
            self._incoming.clear()
            self._drain_scheduled = False
        self._subscription = self._router.subscribe(
            lambda message: self._forward(message, generation),
            self._message_filter,
        )

    def stop(self) -> None:
        if self._subscription is not None:
            self._subscription.cancel()
            self._subscription = None
        with self._bridge_lock:
            self._generation += 1
            self._incoming.clear()
            self._drain_scheduled = False
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        with self._bridge_lock:
            self._queued_count = 0
        if self._configured_loop is None:
            self._loop = None

    close = stop

    async def receive(self, *, timeout: float | None = None) -> MavlinkMessage:
        if timeout is None:
            message = await self._queue.get()
        else:
            if timeout <= 0:
                raise ValueError("MAVLink async receive timeout pozitif olmalı")
            message = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        with self._bridge_lock:
            self._queued_count -= 1
        return message

    def receive_nowait(self) -> MavlinkMessage:
        message = self._queue.get_nowait()
        with self._bridge_lock:
            self._queued_count -= 1
        return message

    def _forward(
        self,
        message: MavlinkMessage,
        generation: int | None = None,
    ) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._bridge_lock:
            current_generation = self._generation
            if generation is not None and generation != current_generation:
                return
            buffered = self._queued_count + len(self._incoming)
            if buffered >= self._maxsize:
                if self._incoming:
                    self._incoming.popleft()
                else:
                    self._dropped_messages += 1
                    return
                self._dropped_messages += 1
            self._incoming.append(message)
            if self._drain_scheduled:
                return
            self._drain_scheduled = True
        try:
            loop.call_soon_threadsafe(self._drain, current_generation)
        except RuntimeError:
            # The loop may close between is_closed() and this thread-safe call.
            with self._bridge_lock:
                if current_generation == self._generation:
                    self._incoming.clear()
                    self._drain_scheduled = False
            return

    def _drain(self, generation: int) -> None:
        while True:
            with self._bridge_lock:
                if generation != self._generation:
                    return
                if not self._incoming:
                    self._drain_scheduled = False
                    return
                message = self._incoming.popleft()
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                else:
                    with self._bridge_lock:
                        self._dropped_messages += 1
                        self._queued_count -= 1
            self._queue.put_nowait(message)
            with self._bridge_lock:
                self._queued_count += 1
