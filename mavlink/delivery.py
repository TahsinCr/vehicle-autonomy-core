"""Bounded synchronous callback worker, shared by all scopes of a runtime."""

from collections import deque
from collections.abc import Callable
import threading
from typing import Any


class CallbackWorker:
    def __init__(self, capacity: int = 1024, action_capacity: int = 1024) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Callback capacity must be a positive integer")
        self.capacity = capacity
        if isinstance(action_capacity, bool) or not isinstance(action_capacity, int) or action_capacity < 1:
            raise ValueError("Action capacity must be a positive integer")
        self.action_capacity = action_capacity
        self.failure: Exception | None = None
        self.on_failure: Callable[[Exception], None] | None = None
        self.dropped = 0
        self._condition = threading.Condition()
        self._queue: deque[tuple[Callable, Any]] = deque()
        self._actions: deque[tuple[Callable, Any]] = deque()
        self._thread: threading.Thread | None = None
        self._running = False
        self._busy = False

    def start(self) -> None:
        with self._condition:
            if self._running:
                self.raise_if_failed()
                return
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Previous callback worker has not stopped")
            self._running = True
            self.failure = None
            self._thread = threading.Thread(target=self._run, name="mavlink-callbacks", daemon=True)
            self._thread.start()

    def raise_if_failed(self) -> None:
        if self.failure is not None:
            raise RuntimeError("Callback delivery failed; stop before restarting") from self.failure

    def submit(self, callback: Callable, event: Any, *, action: bool = False) -> None:
        with self._condition:
            if not self._running or self.failure is not None:
                return
            queue = self._actions if action else self._queue
            if len(queue) >= (self.action_capacity if action else self.capacity):
                if action:
                    self.failure = BufferError("Lifecycle callback queue is full")
                    self._condition.notify_all()
                    return
                queue.popleft()
                self.dropped += 1
            queue.append((callback, event))
            self._condition.notify()

    def _run(self) -> None:
        try:
            self._consume()
        finally:
            if self.failure is not None and self.on_failure is not None:
                try:
                    self.on_failure(self.failure)
                except BaseException:
                    # Keep the original fatal state even if error reporting fails.
                    pass

    def _consume(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._actions or not self._running or self.failure)
                if not self._running or self.failure is not None:
                    self._queue.clear()
                    self._actions.clear()
                    self._condition.notify_all()
                    return
                callback, event = (self._actions or self._queue).popleft()
                self._busy = True
            try:
                callback(event)
            except BaseException as error:
                with self._condition:
                    self.failure = error if isinstance(error, Exception) else RuntimeError(
                        f"Callback worker terminated by {type(error).__name__}: {error}")
            finally:
                with self._condition:
                    self._busy = False
                    self._condition.notify_all()

    def wait_idle(self, timeout: float = 2.0) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: not self._busy and not self._queue and not self._actions, timeout)

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._queue.clear()
            self._actions.clear()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(2.0)
            if thread.is_alive():
                raise TimeoutError("Synchronous callback ignored shutdown")
