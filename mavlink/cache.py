from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Generic, Hashable, TypeVar


T = TypeVar("T")
K = TypeVar("K", bound=Hashable)


class MessageCache(Generic[T, K]):
    """Thread-safe cache storing bounded message history per key."""

    def __init__(self, key: Callable[[T], K], *, per_key_limit: int = 64) -> None:
        if per_key_limit <= 0:
            raise ValueError("per_key_limit pozitif olmalı")
        self._key = key
        self._limit = per_key_limit
        self._items: dict[K, deque[T]] = {}
        self._lock = threading.RLock()

    def add(self, item: T) -> None:
        key = self._key(item)
        with self._lock:
            bucket = self._items.setdefault(key, deque(maxlen=self._limit))
            bucket.append(item)

    def __len__(self) -> int:
        with self._lock:
            return sum(len(bucket) for bucket in self._items.values())

    @property
    def keys(self) -> tuple[K, ...]:
        with self._lock:
            return tuple(self._items)

    def latest(self, key: K) -> T | None:
        with self._lock:
            bucket = self._items.get(key)
            return bucket[-1] if bucket else None

    def all(self, key: K) -> tuple[T, ...]:
        with self._lock:
            return tuple(self._items.get(key, ()))

    def snapshot(self) -> dict[K, tuple[T, ...]]:
        with self._lock:
            return {key: tuple(bucket) for key, bucket in self._items.items()}

    def clear(self, key: K | None = None) -> None:
        with self._lock:
            if key is None:
                self._items.clear()
            else:
                self._items.pop(key, None)
