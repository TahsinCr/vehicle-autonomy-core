from __future__ import annotations

import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Generic, Hashable, TypeVar
from dataclasses import dataclass


T = TypeVar("T")
K = TypeVar("K", bound=Hashable)


@dataclass(frozen=True, slots=True)
class MessageCacheStats:
    keys: int
    messages: int
    evicted_keys: int


class MessageCache(Generic[T, K]):
    """Thread-safe cache storing bounded message history per key."""

    def __init__(
        self,
        key: Callable[[T], K],
        *,
        per_key_limit: int = 64,
        max_keys: int | None = None,
    ) -> None:
        if (
            isinstance(per_key_limit, bool)
            or not isinstance(per_key_limit, int)
            or per_key_limit <= 0
        ):
            raise ValueError("per_key_limit pozitif olmalı")
        if max_keys is not None and (
            isinstance(max_keys, bool) or not isinstance(max_keys, int) or max_keys <= 0
        ):
            raise ValueError("max_keys pozitif bir tamsayı veya None olmalı")
        self._key = key
        self._limit = per_key_limit
        self._max_keys = max_keys
        self._items: OrderedDict[K, deque[T]] = OrderedDict()
        self._lock = threading.RLock()
        self._evicted_keys = 0

    def add(self, item: T) -> None:
        key = self._key(item)
        with self._lock:
            bucket = self._items.get(key)
            if bucket is None:
                if self._max_keys is not None and len(self._items) >= self._max_keys:
                    self._items.popitem(last=False)
                    self._evicted_keys += 1
                bucket = deque(maxlen=self._limit)
                self._items[key] = bucket
            else:
                self._items.move_to_end(key)
            bucket.append(item)

    def __len__(self) -> int:
        with self._lock:
            return sum(len(bucket) for bucket in self._items.values())

    @property
    def keys(self) -> tuple[K, ...]:
        with self._lock:
            return tuple(self._items)

    @property
    def stats(self) -> MessageCacheStats:
        with self._lock:
            return MessageCacheStats(
                keys=len(self._items),
                messages=sum(len(bucket) for bucket in self._items.values()),
                evicted_keys=self._evicted_keys,
            )

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
