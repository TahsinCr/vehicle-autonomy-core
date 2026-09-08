"""Bounded, loss-reporting background writes for optional message storage."""

from __future__ import annotations

import threading
import time
import math
from collections import deque
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class HistoryWriter(Generic[T]):
    def __init__(
        self,
        write: Callable[[tuple[T, ...]], None],
        capacity: int,
        *,
        batch_size: int = 64,
        flush_interval: float = 0.02,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Writer capacity must be a positive integer")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("Writer batch size must be a positive integer")
        if (
            isinstance(flush_interval, bool)
            or not math.isfinite(flush_interval)
            or flush_interval < 0
        ):
            raise ValueError("Writer flush interval must be finite and non-negative")
        self._write = write
        self._capacity = capacity
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._condition = threading.Condition()
        self._queue: deque[T] = deque()
        self._busy = False
        self._submitted = 0
        self._completed = 0
        self._closed = False
        self.failure: Exception | None = None
        self._thread = threading.Thread(target=self._run, name="mavlink-history", daemon=True)
        self._thread.start()

    def submit(self, record: T) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("History writer is closed")
            if self.failure is not None:
                raise RuntimeError("History recording failed") from self.failure
            if len(self._queue) >= self._capacity:
                self.failure = BufferError("History writer queue is full; recording is incomplete")
                raise self.failure
            self._queue.append(record)
            self._submitted += 1
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._closed)
                if not self._queue:
                    return
                deadline = time.monotonic() + self._flush_interval
                while len(self._queue) < self._batch_size and not self._closed:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)
                records = tuple(
                    self._queue.popleft()
                    for _ in range(min(len(self._queue), self._batch_size))
                )
                self._busy = True
            try:
                self._write(records)
            except BaseException as error:
                with self._condition:
                    self.failure = error if isinstance(error, Exception) else RuntimeError(str(error))
            finally:
                with self._condition:
                    self._busy = False
                    self._completed += len(records)
                    self._condition.notify_all()

    def flush(self, timeout: float = 5.0) -> None:
        with self._condition:
            boundary = self._submitted
            if not self._condition.wait_for(lambda: self._completed >= boundary, timeout):
                raise TimeoutError("History writer did not flush")
            if self.failure is not None:
                raise RuntimeError("History recording failed") from self.failure

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(5.0)
        if self._thread.is_alive():
            raise TimeoutError("History writer did not stop")
        self.flush()
