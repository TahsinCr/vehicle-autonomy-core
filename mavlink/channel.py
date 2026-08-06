from __future__ import annotations

import asyncio
import threading

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
        self._configured_loop = loop
        self._loop = loop
        self._subscription: Subscription | None = None
        self._dropped_messages = 0
        self._counter_lock = threading.Lock()

    @property
    def dropped_messages(self) -> int:
        with self._counter_lock:
            return self._dropped_messages

    @property
    def pending_messages(self) -> int:
        return self._queue.qsize()

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
        self._subscription = self._router.subscribe(self._forward, self._message_filter)

    def stop(self) -> None:
        if self._subscription is not None:
            self._subscription.cancel()
            self._subscription = None
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._configured_loop is None:
            self._loop = None

    close = stop

    async def receive(self, *, timeout: float | None = None) -> MavlinkMessage:
        if timeout is None:
            return await self._queue.get()
        if timeout <= 0:
            raise ValueError("MAVLink async receive timeout pozitif olmalı")
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    def receive_nowait(self) -> MavlinkMessage:
        return self._queue.get_nowait()

    def _forward(self, message: MavlinkMessage) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._put_nowait, message)
        except RuntimeError:
            # The loop may close between is_closed() and this thread-safe call.
            return

    def _put_nowait(self, message: MavlinkMessage) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                with self._counter_lock:
                    self._dropped_messages += 1
        self._queue.put_nowait(message)
