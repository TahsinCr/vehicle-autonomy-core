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
        self._maxsize = maxsize
        self._messages: deque[MavlinkMessage] = deque()
        self._available = asyncio.Event()
        self._configured_loop = loop
        self._loop = loop
        self._subscription: Subscription | None = None
        self._dropped_messages = 0
        self._bridge_lock = threading.Lock()
        self._notification_scheduled = False
        self._generation = 0

    @property
    def dropped_messages(self) -> int:
        with self._bridge_lock:
            return self._dropped_messages

    @property
    def pending_messages(self) -> int:
        with self._bridge_lock:
            return len(self._messages)

    def start(self) -> None:
        with self._bridge_lock:
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
            if self._subscription is not None:
                return
            self._generation += 1
            generation = self._generation
            self._messages.clear()
            self._available = asyncio.Event()
            self._notification_scheduled = False
            self._subscription = self._router.subscribe(
                lambda message: self._forward(message, generation),
                self._message_filter,
            )

    def stop(self) -> None:
        with self._bridge_lock:
            subscription = self._subscription
            self._subscription = None
            loop = self._loop
            available = self._available
            self._generation += 1
            generation = self._generation
            self._messages.clear()
            self._notification_scheduled = False
        if subscription is not None:
            subscription.cancel()
        self._schedule_notification(loop, available, generation)
        if self._configured_loop is None:
            with self._bridge_lock:
                self._loop = None

    close = stop

    async def receive(self, *, timeout: float | None = None) -> MavlinkMessage:
        if timeout is not None and timeout <= 0:
            raise ValueError("MAVLink async receive timeout pozitif olmalı")
        pending = self._receive_next()
        return await pending if timeout is None else await asyncio.wait_for(
            pending,
            timeout=timeout,
        )

    async def _receive_next(self) -> MavlinkMessage:
        while True:
            with self._bridge_lock:
                if self._messages:
                    return self._messages.popleft()
                if self._subscription is None:
                    raise RuntimeError("MavlinkAsyncChannel çalışmıyor")
                available = self._available
                available.clear()
            await available.wait()

    def receive_nowait(self) -> MavlinkMessage:
        with self._bridge_lock:
            try:
                return self._messages.popleft()
            except IndexError as exc:
                raise asyncio.QueueEmpty from exc

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
            if len(self._messages) >= self._maxsize:
                self._messages.popleft()
                self._dropped_messages += 1
            self._messages.append(message)
            available = self._available
            if self._notification_scheduled:
                return
            self._notification_scheduled = True
        if not self._schedule_notification(loop, available, current_generation):
            with self._bridge_lock:
                if current_generation == self._generation:
                    self._messages.clear()
                    self._notification_scheduled = False

    def _schedule_notification(
        self,
        loop: asyncio.AbstractEventLoop | None,
        available: asyncio.Event,
        generation: int,
    ) -> bool:
        if loop is None or loop.is_closed():
            return False
        try:
            loop.call_soon_threadsafe(
                self._notify,
                available,
                generation,
            )
            return True
        except RuntimeError:
            return False

    def _notify(self, available: asyncio.Event, generation: int) -> None:
        with self._bridge_lock:
            if generation == self._generation and available is self._available:
                self._notification_scheduled = False
        available.set()
