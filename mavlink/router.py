from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..abstracts import Service
from ..events import EventBus, Subscription
from .cache import MessageCache
from .connection import MavlinkConnection
from .filter import (
    MessagePredicate,
    MessageTypeInput,
    MavlinkMessageFilter,
    coerce_message_filter,
)
from .message import MavlinkMessageEnvelope


@dataclass(frozen=True, slots=True)
class MavlinkRouterStats:
    running: bool
    sequence: int
    received_messages: int
    receive_errors: int
    dispatch_errors: int
    estimated_dropped_messages: int
    delivery_quality: int | None
    started_monotonic: float | None
    last_message_monotonic: float | None


@dataclass(frozen=True, slots=True)
class MavlinkRouterError:
    phase: str
    error: Exception
    envelope: MavlinkMessageEnvelope | None = None


@dataclass(slots=True)
class _Route:
    message_filter: MavlinkMessageFilter
    callback: Callable[[Any], None]


class MavlinkMessageRouter(Service):
    """Single connection reader and filtered MAVLink message backbone.

    ``messages`` remains available for legacy unfiltered subscriptions. New
    consumers should pass MAVLink metadata filters to ``subscribe`` so only
    relevant callbacks run.
    """

    def __init__(
        self,
        connection: MavlinkConnection,
        *,
        history_limit: int = 512,
        cache_per_type: int = 64,
        poll_timeout: float = 0.25,
        error_backoff: float = 0.1,
        stop_timeout: float = 2.0,
    ) -> None:
        if history_limit <= 0:
            raise ValueError("history_limit pozitif olmalı")
        if poll_timeout <= 0:
            raise ValueError("poll_timeout pozitif olmalı")
        if error_backoff < 0:
            raise ValueError("error_backoff negatif olamaz")
        if stop_timeout <= 0:
            raise ValueError("stop_timeout pozitif olmalı")
        self.connection = connection
        self.messages = EventBus[Any]()
        self.envelopes = EventBus[MavlinkMessageEnvelope]()
        self.errors = EventBus[MavlinkRouterError]()
        self.cache = MessageCache[Any, str](
            lambda message: str(message.get_type()).upper(),
            per_key_limit=cache_per_type,
        )
        self._history: deque[MavlinkMessageEnvelope] = deque(maxlen=history_limit)
        self._poll_timeout = poll_timeout
        self._error_backoff = error_backoff
        self._stop_timeout = float(stop_timeout)
        self._condition = threading.Condition(threading.RLock())
        self._lifecycle_lock = threading.RLock()
        self._route_lock = threading.RLock()
        self._routes_by_type: dict[str, dict[int, _Route]] = {}
        self._wildcard_routes: dict[int, _Route] = {}
        self._next_route_id = 0
        self._sequence = 0
        self._received_messages = 0
        self._receive_errors = 0
        self._dispatch_errors = 0
        self._estimated_dropped_messages = 0
        self._source_sequences: dict[tuple[int, int], int] = {}
        self._delivery_window: deque[tuple[int, int]] = deque(maxlen=256)
        self._started_monotonic: float | None = None
        self._last_message_monotonic: float | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        with self._condition:
            return self._running

    @property
    def sequence(self) -> int:
        """Return the last sequence used as a response boundary before a request."""
        with self._condition:
            return self._sequence

    @property
    def stats(self) -> MavlinkRouterStats:
        with self._condition:
            return MavlinkRouterStats(
                running=self._running,
                sequence=self._sequence,
                received_messages=self._received_messages,
                receive_errors=self._receive_errors,
                dispatch_errors=self._dispatch_errors,
                estimated_dropped_messages=self._estimated_dropped_messages,
                delivery_quality=self._delivery_quality(),
                started_monotonic=self._started_monotonic,
                last_message_monotonic=self._last_message_monotonic,
            )

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                if self._stop_event.is_set():
                    raise RuntimeError("MAVLink router hâlâ durduruluyor")
                return
            self.connection.start()
            self._stop_event.clear()
            with self._condition:
                self._source_sequences.clear()
                self._delivery_window.clear()
                self._estimated_dropped_messages = 0
                self._running = True
                self._started_monotonic = time.monotonic()
            self._thread = threading.Thread(
                target=self._read_loop,
                name="MavlinkRouter",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_event.set()
            thread = self._thread
        if thread is threading.current_thread():
            raise RuntimeError("MAVLink router kendi receive thread'inden durdurulamaz")
        if thread is not None:
            thread.join(timeout=self._stop_timeout)
            if thread.is_alive():
                raise TimeoutError(
                    "MAVLink router receive thread'i zamanında durmadı; "
                    "bağlantı güvenlik için açık bırakıldı"
                )

        try:
            self.connection.stop()
        finally:
            with self._lifecycle_lock:
                if self._thread is thread:
                    self._thread = None
            with self._condition:
                self._running = False
                self._condition.notify_all()

    close = stop

    def subscribe(
        self,
        callback: Callable[[Any], None],
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
    ) -> Subscription:
        """Bind a callback with type, source, component, ID and condition filters."""
        if not callable(callback):
            raise TypeError("MAVLink callback callable olmalı")
        normalized_filter = coerce_message_filter(message_filter)
        route = _Route(normalized_filter, callback)
        with self._route_lock:
            route_id = self._next_route_id
            self._next_route_id += 1
            if normalized_filter.message_types is None:
                self._wildcard_routes[route_id] = route
            else:
                for message_type in normalized_filter.message_types:
                    self._routes_by_type.setdefault(message_type, {})[route_id] = route

        def cancel() -> None:
            with self._route_lock:
                self._wildcard_routes.pop(route_id, None)
                empty_types: list[str] = []
                for message_type, routes in self._routes_by_type.items():
                    routes.pop(route_id, None)
                    if not routes:
                        empty_types.append(message_type)
                for message_type in empty_types:
                    self._routes_by_type.pop(message_type, None)

        return Subscription(route_id, cancel)

    def latest(
        self,
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
    ) -> Any | None:
        normalized_filter = coerce_message_filter(message_filter)
        with self._condition:
            history = tuple(reversed(self._history))
        for envelope in history:
            if self._matches(normalized_filter, envelope):
                return envelope.message
        return None

    def history(
        self,
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[MavlinkMessageEnvelope, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("history limit pozitif olmalı")
        normalized_filter = coerce_message_filter(message_filter)
        with self._condition:
            history = tuple(self._history)
        filtered = tuple(
            envelope for envelope in history if self._matches(normalized_filter, envelope)
        )
        return filtered[-limit:] if limit is not None else filtered

    def wait_for(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        *,
        predicate: MessagePredicate | None = None,
        timeout: float = 3.0,
        after_sequence: int | None = None,
    ) -> Any:
        if timeout <= 0:
            raise ValueError("MAVLink wait timeout pozitif olmalı")
        message_filter = coerce_message_filter(message_types)
        deadline = time.monotonic() + timeout
        with self._condition:
            if not self._running:
                raise RuntimeError("MAVLink router çalışmıyor")
            cursor = self._sequence if after_sequence is None else after_sequence

        while True:
            with self._condition:
                candidates = tuple(
                    envelope for envelope in self._history if envelope.sequence > cursor
                )
                observed_sequence = self._sequence
            for envelope in candidates:
                if self._matches(message_filter, envelope) and (
                    predicate is None or predicate(envelope.message)
                ):
                    return envelope.message

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                expected = message_filter.message_types or frozenset({"*"})
                raise TimeoutError(f"MAVLink mesajı beklenirken zaman aşımı: {sorted(expected)}")
            with self._condition:
                if self._sequence > observed_sequence:
                    continue
                if not self._running:
                    raise ConnectionError("MAVLink router mesaj beklenirken durduruldu")
                self._condition.wait(remaining)

    def _read_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    message = self.connection.receive(
                        blocking=True,
                        timeout=self._poll_timeout,
                    )
                except Exception as exc:
                    if self._stop_event.is_set():
                        return
                    with self._condition:
                        self._receive_errors += 1
                    self._publish_error(MavlinkRouterError("receive", exc))
                    if self._stop_event.wait(self._error_backoff):
                        return
                    continue
                if message is None:
                    continue
                with self._condition:
                    self._sequence += 1
                    envelope = MavlinkMessageEnvelope.wrap(self._sequence, message)
                    self._history.append(envelope)
                    self._received_messages += 1
                    self._record_delivery(envelope)
                    self._last_message_monotonic = envelope.received_monotonic
                    self._condition.notify_all()
                self.cache.add(message)
                self._dispatch(envelope)
        finally:
            with self._condition:
                self._running = False
                self._condition.notify_all()

    def _record_delivery(self, envelope: MavlinkMessageEnvelope) -> None:
        source_system = envelope.source_system
        source_component = envelope.source_component
        sequence = self._message_sequence(envelope.message)
        if source_system is None or source_component is None or sequence is None:
            return
        key = (source_system, source_component)
        previous = self._source_sequences.get(key)
        self._source_sequences[key] = sequence
        if previous is None:
            self._delivery_window.append((1, 0))
            return
        delta = (sequence - previous) & 0xFF
        # Backward jumps larger than 64 indicate a restart or out-of-order
        # packet and must not be counted as real loss that lowers the metric.
        dropped = delta - 1 if 1 < delta <= 64 else 0
        self._estimated_dropped_messages += dropped
        self._delivery_window.append((1, dropped))

    def _delivery_quality(self) -> int | None:
        if not self._delivery_window:
            return None
        received = sum(item[0] for item in self._delivery_window)
        dropped = sum(item[1] for item in self._delivery_window)
        total = received + dropped
        return round(received / total * 100.0) if total else None

    @staticmethod
    def _message_sequence(message: Any) -> int | None:
        getter = getattr(message, "get_seq", None)
        if callable(getter):
            try:
                return int(getter()) & 0xFF
            except (TypeError, ValueError):
                return None
        header = getattr(message, "_header", None)
        value = getattr(header, "seq", None)
        try:
            return int(value) & 0xFF if value is not None else None
        except (TypeError, ValueError):
            return None

    def _dispatch(self, envelope: MavlinkMessageEnvelope) -> None:
        compatibility_errors = (
            *self.envelopes.publish(envelope).errors,
            *self.messages.publish(envelope.message).errors,
        )
        for exc in compatibility_errors:
            self._record_dispatch_error(exc, envelope)

        with self._route_lock:
            candidates = {
                **self._wildcard_routes,
                **self._routes_by_type.get(envelope.message_type, {}),
            }

        condition_results: dict[str, bool] = {}

        def evaluate(condition: str) -> bool:
            if condition not in condition_results:
                condition_results[condition] = self.connection.evaluate_condition(condition)
            return condition_results[condition]

        for route in candidates.values():
            try:
                if route.message_filter.matches(
                    envelope.message,
                    condition_evaluator=evaluate,
                    metadata=envelope,
                ):
                    route.callback(envelope.message)
            except Exception as exc:
                self._record_dispatch_error(exc, envelope)

    def _matches(
        self,
        message_filter: MavlinkMessageFilter,
        envelope: MavlinkMessageEnvelope,
    ) -> bool:
        try:
            return message_filter.matches(
                envelope.message,
                condition_evaluator=self.connection.evaluate_condition,
                metadata=envelope,
            )
        except Exception as exc:
            self._record_dispatch_error(exc, envelope)
            return False

    def _record_dispatch_error(
        self,
        error: Exception,
        envelope: MavlinkMessageEnvelope,
    ) -> None:
        with self._condition:
            self._dispatch_errors += 1
        self._publish_error(MavlinkRouterError("dispatch", error, envelope))

    def _publish_error(self, error: MavlinkRouterError) -> None:
        self.errors.publish(error)
