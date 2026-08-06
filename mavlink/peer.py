from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from ..abstracts import Service
from ..events import EventBus, Subscription
from .application import (
    MavlinkApplicationChannel,
    MavlinkApplicationPacket,
)


TargetValue = int | Callable[[], int]
PayloadFactory = Mapping[str, Any] | Callable[[], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class MavlinkApplicationPeerState:
    """Describe one application peer carried by a shared MAVLink transport."""

    running: bool = False
    transport_available: bool = False
    alive: bool = False
    last_seen_at: float | None = None
    last_liveness_at: float | None = None
    round_trip_ms: float | None = None
    packets_in: int = 0
    packets_out: int = 0
    last_packet_type: str = ""
    last_error: str = ""


@dataclass(frozen=True, slots=True)
class MavlinkApplicationResponse:
    """Pair a request with its correlated application response."""

    request: MavlinkApplicationPacket
    response: MavlinkApplicationPacket
    round_trip_ms: float


@dataclass(slots=True)
class _PendingRequest:
    event: threading.Event
    response_types: frozenset[str]
    started_monotonic: float
    response: MavlinkApplicationPacket | None = None
    error: str = ""


class MavlinkApplicationPeer(Service):
    """Manage liveness and correlated messages over one application channel.

    The peer owns no serial or network transport. It uses the supplied
    ``MavlinkApplicationChannel``, which in turn subscribes to the existing
    ``MavlinkClient`` router. The same class can therefore run on the GCS and
    the onboard computer without creating a second MAVLink reader.
    """

    LIVENESS_TYPES = frozenset(
        {"system.heartbeat", "system.ping", "system.pong"}
    )

    def __init__(
        self,
        channel: MavlinkApplicationChannel,
        *,
        role: str,
        target_system: TargetValue = 0,
        target_component: TargetValue = 0,
        transport_available: Callable[[], bool] | None = None,
        heartbeat_payload: PayloadFactory | None = None,
        heartbeat_interval: float = 1.0,
        heartbeat_timeout: float = 12.0,
        stop_timeout: float = 1.0,
    ) -> None:
        normalized_role = str(role).strip().lower()
        if not normalized_role:
            raise ValueError("MAVLink application peer role cannot be empty")
        if heartbeat_interval <= 0 or heartbeat_timeout <= 0:
            raise ValueError("MAVLink application peer timeouts must be positive")
        if heartbeat_interval >= heartbeat_timeout:
            raise ValueError("Heartbeat interval must be shorter than its timeout")
        if stop_timeout <= 0:
            raise ValueError("MAVLink application peer stop timeout must be positive")

        self._channel = channel
        self._role = normalized_role
        self._target_system = target_system
        self._target_component = target_component
        self._transport_available = transport_available or (lambda: True)
        self._heartbeat_payload = heartbeat_payload or {}
        self._heartbeat_interval = float(heartbeat_interval)
        self._heartbeat_timeout = float(heartbeat_timeout)
        self._stop_timeout = float(stop_timeout)
        self._state = MavlinkApplicationPeerState()
        self._pending: dict[int, _PendingRequest] = {}
        self._probes: dict[int, float] = {}
        self._last_liveness_monotonic = 0.0
        self._subscriptions: list[Subscription] = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._monitor_thread: threading.Thread | None = None

        self.packets = EventBus[MavlinkApplicationPacket]()
        self.changed = EventBus[MavlinkApplicationPeerState]()
        self.errors = EventBus[Exception]()

    @property
    def state(self) -> MavlinkApplicationPeerState:
        with self._lock:
            return replace(self._state)

    @property
    def running(self) -> bool:
        with self._lock:
            return self._state.running

    @property
    def alive(self) -> bool:
        with self._lock:
            return self._state.alive

    def start(self) -> None:
        with self._lock:
            if self._state.running:
                return
            if self._monitor_thread is not None and self._monitor_thread.is_alive():
                raise RuntimeError(
                    "MAVLink application peer monitor thread is still stopping"
                )
            self._state = replace(
                self._state,
                running=True,
                transport_available=self._transport_ready(),
                last_error="",
            )
        self._subscriptions = [
            self._channel.packets.subscribe(self._on_packet),
            self._channel.errors.subscribe(self._on_error),
        ]
        try:
            self._channel.start()
        except Exception:
            for subscription in self._subscriptions:
                subscription.cancel()
            self._subscriptions.clear()
            with self._lock:
                self._state = replace(self._state, running=False)
            raise

        self._stop.clear()
        self._wake.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor,
            name=f"MavlinkApplicationPeer[{self._role}]",
            daemon=True,
        )
        self._monitor_thread.start()
        self.changed.publish(self.state)
        self._wake.set()

    def stop(self) -> None:
        with self._lock:
            was_running = self._state.running
            if was_running:
                self._state = replace(
                    self._state,
                    running=False,
                    transport_available=False,
                    alive=False,
                    last_error="Application peer stopped",
                )
                pending = tuple(self._pending.values())
                self._pending.clear()
                self._probes.clear()
            else:
                pending = ()
            thread = self._monitor_thread
        if not was_running and (thread is None or not thread.is_alive()):
            return
        self._stop.set()
        self._wake.set()
        for item in pending:
            item.error = "Application peer stopped"
            item.event.set()
        if was_running:
            for subscription in self._subscriptions:
                subscription.cancel()
            self._subscriptions.clear()
            self._channel.stop()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._stop_timeout)
            if thread.is_alive():
                if was_running:
                    self.changed.publish(self.state)
                raise TimeoutError(
                    "MAVLink application peer monitor thread did not stop in time"
                )
        elif thread is threading.current_thread():
            raise RuntimeError("Application peer cannot stop from its monitor thread")
        with self._lock:
            if self._monitor_thread is thread:
                self._monitor_thread = None
        if was_running:
            self.changed.publish(self.state)

    def refresh_transport(self) -> None:
        """Re-evaluate transport availability without polling the serial link."""

        self._set_transport_state(self._transport_ready())
        self._wake.set()

    def send(
        self,
        packet_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        packet_id: int | None = None,
        target_system: int | None = None,
        target_component: int | None = None,
        expects_response: bool = False,
    ) -> MavlinkApplicationPacket:
        with self._lock:
            if not self._state.running:
                raise ConnectionError("MAVLink application peer is not running")
        if not self._transport_ready():
            self.refresh_transport()
            raise ConnectionError("MAVLink transport is unavailable")

        packet = self._channel.send(
            packet_type,
            payload,
            packet_id=packet_id,
            target_system=(
                self._resolve_target(self._target_system)
                if target_system is None
                else int(target_system)
            ),
            target_component=(
                self._resolve_target(self._target_component)
                if target_component is None
                else int(target_component)
            ),
            expects_response=expects_response,
        )
        with self._lock:
            last_error = self._state.last_error
            self._state = replace(
                self._state,
                transport_available=True,
                packets_out=self._state.packets_out + 1,
                last_error=(
                    "" if last_error == "MAVLink transport unavailable" else last_error
                ),
            )
            state = replace(self._state)
        self.changed.publish(state)
        return packet

    def request(
        self,
        packet_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        response_types: str | tuple[str, ...] | frozenset[str],
        timeout: float,
        target_system: int | None = None,
        target_component: int | None = None,
        on_sent: Callable[[MavlinkApplicationPacket], None] | None = None,
    ) -> MavlinkApplicationResponse:
        """Send a request and wait only for a response with its request ID."""

        if timeout <= 0:
            raise ValueError("MAVLink application request timeout must be positive")
        normalized_responses = self._normalize_types(response_types)
        packet_id = self._reserve_packet_id()
        pending = _PendingRequest(
            threading.Event(),
            normalized_responses,
            time.monotonic(),
        )
        with self._lock:
            if not self._state.running:
                raise ConnectionError("MAVLink application peer is not running")
            self._pending[packet_id] = pending
        try:
            request = self.send(
                packet_type,
                payload,
                packet_id=packet_id,
                target_system=target_system,
                target_component=target_component,
                expects_response=True,
            )
            if on_sent is not None:
                try:
                    on_sent(request)
                except Exception as exc:
                    self.errors.publish(exc)
            if not pending.event.wait(float(timeout)):
                raise TimeoutError(
                    f"MAVLink application response timed out: {request.packet_type}"
                )
            if pending.error:
                raise ConnectionError(pending.error)
            response = pending.response
            if response is None:
                raise TimeoutError("MAVLink application response was empty")
            return MavlinkApplicationResponse(
                request,
                response,
                max(0.0, (time.monotonic() - pending.started_monotonic) * 1000.0),
            )
        finally:
            with self._lock:
                self._pending.pop(packet_id, None)

    def probe(self) -> MavlinkApplicationPacket:
        """Send one status-bearing liveness probe and measure its round trip."""

        probe_payload = dict(self._payload())
        probe_payload.setdefault("role", self._role)
        probe_payload.setdefault("health", "ok")
        probe_id = self._reserve_packet_id()
        with self._lock:
            self._probes[probe_id] = time.monotonic()
        try:
            return self.send(
                "system.ping",
                probe_payload,
                packet_id=probe_id,
            )
        except Exception:
            with self._lock:
                self._probes.pop(probe_id, None)
            raise

    def _on_packet(self, packet: MavlinkApplicationPacket) -> None:
        now_monotonic = time.monotonic()
        now_epoch = time.time()
        response_to = self._response_request_id(packet)
        with self._lock:
            if not self._state.running:
                return
            liveness = packet.packet_type in self.LIVENESS_TYPES
            if liveness:
                self._last_liveness_monotonic = now_monotonic
            round_trip_ms = self._state.round_trip_ms
            probe_started = (
                self._probes.pop(response_to, None)
                if packet.packet_type == "system.pong" and response_to is not None
                else None
            )
            if probe_started is not None:
                round_trip_ms = max(0.0, (now_monotonic - probe_started) * 1000.0)
            pending = self._pending.get(response_to) if response_to is not None else None
            if pending is not None and packet.packet_type in pending.response_types:
                pending.response = packet
                pending.event.set()
            self._state = replace(
                self._state,
                transport_available=True,
                alive=True if liveness else self._state.alive,
                last_seen_at=now_epoch,
                last_liveness_at=now_epoch if liveness else self._state.last_liveness_at,
                round_trip_ms=round_trip_ms,
                packets_in=self._state.packets_in + 1,
                last_packet_type=packet.packet_type,
                last_error="",
            )
            state = replace(self._state)

        self.changed.publish(state)
        self.packets.publish(packet)
        if packet.packet_type == "system.ping":
            try:
                response_payload = dict(self._payload())
                response_payload.update(
                    {
                        "request_id": packet.packet_id,
                        "role": self._role,
                    }
                )
                self.send(
                    "system.pong",
                    response_payload,
                    target_system=int(packet.source_system or 0),
                    target_component=int(packet.source_component or 0),
                )
            except Exception as exc:
                self._on_error(exc)

    def _monitor(self) -> None:
        next_probe = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            ready = self._transport_ready()
            self._set_transport_state(ready)
            if ready and now >= next_probe:
                try:
                    self.probe()
                except Exception as exc:
                    self._on_error(exc)
                next_probe = now + self._heartbeat_interval
            elif not ready:
                next_probe = now
            self._expire_liveness()
            self._prune_probes(now)

            wait_s = (
                max(0.05, min(self._heartbeat_interval, next_probe - time.monotonic()))
                if ready
                else self._heartbeat_interval
            )
            self._wake.wait(wait_s)
            self._wake.clear()

    def _expire_liveness(self) -> None:
        now_monotonic = time.monotonic()
        with self._lock:
            state = self._state
            expired = bool(
                state.alive
                and (
                    not state.transport_available
                    or self._last_liveness_monotonic <= 0
                    or now_monotonic - self._last_liveness_monotonic
                    > self._heartbeat_timeout
                )
            )
            if not expired:
                return
            age = (
                max(0.0, now_monotonic - self._last_liveness_monotonic)
                if self._last_liveness_monotonic > 0
                else self._heartbeat_timeout
            )
            self._state = replace(
                state,
                alive=False,
                last_error=(
                    "MAVLink transport unavailable"
                    if not state.transport_available
                    else f"Application peer heartbeat timed out after {age:.1f} seconds"
                ),
            )
            updated = replace(self._state)
        self.changed.publish(updated)

    def _set_transport_state(self, ready: bool) -> None:
        pending: tuple[_PendingRequest, ...] = ()
        with self._lock:
            state = self._state
            if not state.running:
                return
            if state.transport_available == ready and (ready or not state.alive):
                return
            if not ready:
                pending = tuple(self._pending.values())
                self._probes.clear()
            self._state = replace(
                state,
                transport_available=ready,
                alive=state.alive if ready else False,
                last_error=state.last_error if ready else "MAVLink transport unavailable",
            )
            updated = replace(self._state)
        for item in pending:
            item.error = "MAVLink transport unavailable"
            item.event.set()
        self.changed.publish(updated)

    def _prune_probes(self, now: float) -> None:
        deadline = now - self._heartbeat_timeout
        with self._lock:
            self._probes = {
                packet_id: started
                for packet_id, started in self._probes.items()
                if started >= deadline
            }

    def _on_error(self, error: Exception) -> None:
        with self._lock:
            if not self._state.running:
                return
        self._update_state(last_error=str(error))
        self.errors.publish(error)

    def _update_state(self, **changes: Any) -> None:
        with self._lock:
            updated = replace(self._state, **changes)
            if updated == self._state:
                return
            self._state = updated
            state = replace(updated)
        self.changed.publish(state)

    def _reserve_packet_id(self) -> int:
        while True:
            packet_id = secrets.randbits(32) or 1
            with self._lock:
                if packet_id not in self._pending and packet_id not in self._probes:
                    return packet_id

    def _payload(self) -> Mapping[str, Any]:
        payload = (
            self._heartbeat_payload()
            if callable(self._heartbeat_payload)
            else self._heartbeat_payload
        )
        return payload if isinstance(payload, Mapping) else {}

    def _transport_ready(self) -> bool:
        try:
            return bool(self._transport_available())
        except Exception:
            return False

    @staticmethod
    def _resolve_target(value: TargetValue) -> int:
        resolved = int(value() if callable(value) else value)
        if not 0 <= resolved <= 255:
            raise ValueError("MAVLink target system/component must be in range 0..255")
        return resolved

    @staticmethod
    def _normalize_types(
        values: str | tuple[str, ...] | frozenset[str],
    ) -> frozenset[str]:
        items = (values,) if isinstance(values, str) else values
        normalized = frozenset(str(item).strip().lower() for item in items)
        if not normalized or "" in normalized:
            raise ValueError("MAVLink application response types cannot be empty")
        return normalized

    @staticmethod
    def _response_request_id(packet: MavlinkApplicationPacket) -> int | None:
        value = packet.payload.get("request_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
