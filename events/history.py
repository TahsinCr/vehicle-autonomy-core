"""Optional bounded in-memory history for event buses."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import deque
from typing import Generic, TypeVar

from .filtering import EventFilter


T = TypeVar("T")


class EventHistory(Generic[T], ABC):
    @abstractmethod
    def append(self, event: T) -> None: ...

    @abstractmethod
    def latest(self, event_filter: EventFilter[T] | None = None) -> T | None: ...

    @abstractmethod
    def query(
        self,
        event_filter: EventFilter[T] | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[T, ...]: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def __len__(self) -> int: ...


class MemoryEventHistory(EventHistory[T]):
    """Thread-safe bounded history preserving publication order."""

    def __init__(self, capacity: int = 1_000) -> None:
        if int(capacity) <= 0:
            raise ValueError("Event history capacity must be positive")
        self._events: deque[T] = deque(maxlen=int(capacity))
        self._lock = threading.RLock()

    @property
    def capacity(self) -> int:
        return self._events.maxlen or 0

    def append(self, event: T) -> None:
        with self._lock:
            self._events.append(event)

    def latest(self, event_filter: EventFilter[T] | None = None) -> T | None:
        matcher = event_filter or EventFilter()
        with self._lock:
            events = tuple(reversed(self._events))
        return next((event for event in events if matcher.matches(event)), None)

    def query(
        self,
        event_filter: EventFilter[T] | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[T, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("Event history query limit must be positive")
        matcher = event_filter or EventFilter()
        with self._lock:
            events = tuple(self._events)
        matched = tuple(event for event in events if matcher.matches(event))
        return matched[-limit:] if limit is not None else matched

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
