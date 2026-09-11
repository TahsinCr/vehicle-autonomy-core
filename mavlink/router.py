from __future__ import annotations

import inspect
import threading
import time
from collections import OrderedDict, deque
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
    filtered_messages: int = 0
    state_evictions: int = 0
    cached_state_keys: int = 0


@dataclass(frozen=True, slots=True)
class MavlinkRouterError:
    phase: str
    error: Exception
    envelope: MavlinkMessageEnvelope | None = None


@dataclass(slots=True)
class _Route:
    message_filter: MavlinkMessageFilter
    callback: Callable[[Any], None]


MavlinkIngressFilter = Callable[[MavlinkMessageEnvelope], bool]


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
        state_capacity: int | None = None,
        source_capacity: int | None = None,
    ) -> None:
        if history_limit <= 0:
            raise ValueError("history_limit pozitif olmalı")
        if poll_timeout <= 0:
            raise ValueError("poll_timeout pozitif olmalı")
        if error_backoff < 0:
            raise ValueError("error_backoff negatif olamaz")
        if stop_timeout <= 0:
            raise ValueError("stop_timeout pozitif olmalı")
        for name, value in (("state_capacity", state_capacity), ("source_capacity", source_capacity)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer or None")
        self.connection = connection
        self.messages = EventBus[Any]()
        self.envelopes = EventBus[MavlinkMessageEnvelope]()
        self.errors = EventBus[MavlinkRouterError]()
        self.cache = MessageCache[Any, str](
            lambda message: str(message.get_type()).upper(),
            per_key_limit=cache_per_type,
            max_keys=state_capacity,
        )
        self._history: deque[MavlinkMessageEnvelope] = deque(maxlen=history_limit)
        self._latest: OrderedDict[tuple, MavlinkMessageEnvelope] = OrderedDict()
        self._state_capacity = state_capacity
        self._source_capacity = source_capacity
        self._poll_timeout = poll_timeout
        self._error_backoff = error_backoff
        self._stop_timeout = float(stop_timeout)
        self._condition = threading.Condition(threading.RLock())
        self._lifecycle_lock = threading.RLock()
        self._route_lock = threading.RLock()
        self._filter_lock = threading.RLock()
        self._filters: dict[int, MavlinkIngressFilter] = {}
        self._filter_snapshot: tuple[MavlinkIngressFilter, ...] = ()
        self._next_filter_id = 0
        self._routes_by_type: dict[str, dict[int, _Route]] = {}
        self._wildcard_routes: dict[int, _Route] = {}
        self._next_route_id = 0
        self._sequence = 0
        self._received_messages = 0
        self._receive_errors = 0
        self._dispatch_errors = 0
        self._filtered_messages = 0
        self._state_evictions = 0
        self._estimated_dropped_messages = 0
        self._source_sequences: dict[tuple[int, int], int] = {}
        self._source_message_state: OrderedDict[tuple[int | None, int | None], dict[str, Any]] = OrderedDict()
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
                filtered_messages=self._filtered_messages,
                state_evictions=self._state_evictions,
                cached_state_keys=len(self._latest),
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
                self._source_message_state.clear()
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

    def add_filter(self, predicate: MavlinkIngressFilter) -> Subscription:
        """Accept messages that pass every registered ingress predicate.

        The returned subscription can be cancelled. The same method can be
        used directly or as ``@router.add_filter``.
        """

        if not callable(predicate) or inspect.iscoroutinefunction(predicate):
            raise TypeError("MAVLink ingress filter must be a synchronous callable")
        with self._filter_lock:
            filter_id = self._next_filter_id
            self._next_filter_id += 1
            self._filters[filter_id] = predicate
            self._filter_snapshot = tuple(self._filters.values())

        def cancel() -> None:
            with self._filter_lock:
                self._filters.pop(filter_id, None)
                self._filter_snapshot = tuple(self._filters.values())

        return Subscription(filter_id, cancel)

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
        self._reject_historical_condition(normalized_filter)
        with self._condition:
            if (
                normalized_filter.message_types is not None
                and len(normalized_filter.message_types) == 1
                and normalized_filter.source_systems is not None
                and len(normalized_filter.source_systems) == 1
                and normalized_filter.source_components is not None
                and len(normalized_filter.source_components) == 1
            ):
                envelope = self._latest.get(
                    (
                        next(iter(normalized_filter.source_systems)),
                        next(iter(normalized_filter.source_components)),
                        next(iter(normalized_filter.message_types)),
                    )
                )
                candidates = () if envelope is None else (envelope,)
            else:
                candidates = tuple(self._latest.values())
        best: MavlinkMessageEnvelope | None = None
        for envelope in candidates:
            if (
                (best is None or envelope.sequence > best.sequence)
                and self._matches(normalized_filter, envelope)
            ):
                best = envelope
        return None if best is None else best.message

    def history(
        self,
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[MavlinkMessageEnvelope, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("history limit pozitif olmalı")
        normalized_filter = coerce_message_filter(message_filter)
        self._reject_historical_condition(normalized_filter)
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
        self._reject_historical_condition(message_filter)
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
            cursor = observed_sequence

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
                if not self._accept(envelope):
                    with self._condition:
                        self._filtered_messages += 1
                    continue
                with self._condition:
                    self._history.append(envelope)
                    latest_key = (
                        envelope.source_system,
                        envelope.source_component,
                        envelope.message_type,
                    )
                    if latest_key in self._latest:
                        self._latest.move_to_end(latest_key)
                    elif (
                        self._state_capacity is not None
                        and len(self._latest) >= self._state_capacity
                    ):
                        self._latest.popitem(last=False)
                        self._state_evictions += 1
                    self._latest[latest_key] = envelope

                    source_key = (envelope.source_system, envelope.source_component)
                    state = self._source_message_state.get(source_key)
                    if state is None:
                        if (
                            self._source_capacity is not None
                            and len(self._source_message_state) >= self._source_capacity
                        ):
                            expired_source, _ = self._source_message_state.popitem(last=False)
                            self._source_sequences.pop(expired_source, None)
                            expired_latest = tuple(
                                key for key in self._latest if key[:2] == expired_source
                            )
                            for key in expired_latest:
                                self._latest.pop(key, None)
                            self._state_evictions += 1 + len(expired_latest)
                        state = {}
                        self._source_message_state[source_key] = state
                    else:
                        self._source_message_state.move_to_end(source_key)
                    state[envelope.message_type] = envelope.message
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

    def _accept(self, envelope: MavlinkMessageEnvelope) -> bool:
        # Writes replace the immutable tuple under the filter lock. Reading
        # the current tuple keeps the receive hot path lock-free.
        for predicate in self._filter_snapshot:
            try:
                accepted = predicate(envelope)
                if inspect.isawaitable(accepted):
                    if inspect.iscoroutine(accepted):
                        accepted.close()
                    raise TypeError("MAVLink ingress filter returned an awaitable")
                if not accepted:
                    return False
            except Exception as exc:
                self._record_dispatch_error(exc, envelope, phase="filter")
                return False
        return True

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
            candidates = (
                *self._wildcard_routes.values(),
                *self._routes_by_type.get(envelope.message_type, {}).values(),
            )

        condition_results: dict[str, bool] = {}

        def evaluate(condition: str) -> bool:
            if condition not in condition_results:
                with self._condition:
                    state = dict(
                        self._source_message_state.get(
                            (envelope.source_system, envelope.source_component), {}
                        )
                    )
                evaluator = getattr(self.connection, "evaluate_condition_for_state", None)
                condition_results[condition] = (
                    evaluator(condition, state)
                    if callable(evaluator)
                    else self.connection.evaluate_condition(condition)
                )
            return condition_results[condition]

        for route in candidates:
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
            with self._condition:
                state = dict(
                    self._source_message_state.get(
                        (envelope.source_system, envelope.source_component), {}
                    )
                )
            return message_filter.matches(
                envelope.message,
                condition_evaluator=lambda condition: self._evaluate_condition(
                    condition, state
                ),
                metadata=envelope,
            )
        except Exception as exc:
            self._record_dispatch_error(exc, envelope)
            return False

    def _evaluate_condition(self, condition: str, state: dict[str, Any]) -> bool:
        evaluator = getattr(self.connection, "evaluate_condition_for_state", None)
        if callable(evaluator):
            return bool(evaluator(condition, state))
        return bool(self.connection.evaluate_condition(condition))

    @staticmethod
    def _reject_historical_condition(
        message_filter: MavlinkMessageFilter,
    ) -> None:
        if message_filter.condition is not None:
            raise ValueError(
                "Native MAVLink condition is only causal for live subscriptions; "
                "use predicate for latest, history, or wait_for queries"
            )

    def _record_dispatch_error(
        self,
        error: Exception,
        envelope: MavlinkMessageEnvelope,
        *,
        phase: str = "dispatch",
    ) -> None:
        with self._condition:
            self._dispatch_errors += 1
        self._publish_error(MavlinkRouterError(phase, error, envelope))

    def _publish_error(self, error: MavlinkRouterError) -> None:
        self.errors.publish(error)
