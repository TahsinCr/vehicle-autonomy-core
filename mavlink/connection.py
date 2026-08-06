from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ..abstracts import Service
from ..events import EventBus
from .endpoint import MavlinkEndpoint
from .filter import MessageTypeInput, normalize_message_types


ConnectionFactory = Callable[[MavlinkEndpoint], Any]


class MavlinkUnavailableError(RuntimeError):
    pass


class MavlinkConnection(Service):
    """Own a pymavlink connection and provide thread-safe I/O access."""

    UDP_DISCOVERY_INTERVAL_S = 1.0

    def __init__(
        self,
        endpoint: MavlinkEndpoint,
        *,
        connection_factory: ConnectionFactory | None = None,
        mavutil_module: Any | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.connection_changed = EventBus[bool]()
        self.errors = EventBus[Exception]()
        self._connection: Any | None = None
        self._connection_factory = connection_factory
        self._mavutil_module = mavutil_module
        self._lifecycle_lock = threading.RLock()
        self._receive_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._sent_messages = 0

    @property
    def is_connected(self) -> bool:
        with self._lifecycle_lock:
            return self._connection is not None

    @property
    def raw(self) -> Any:
        with self._lifecycle_lock:
            if self._connection is None:
                raise ConnectionError("MAVLink bağlantısı açık değil")
            return self._connection

    @property
    def target_system(self) -> int:
        return int(getattr(self.raw, "target_system", 0) or 1)

    @property
    def target_component(self) -> int:
        return int(getattr(self.raw, "target_component", 0) or 1)

    @property
    def message_state(self) -> dict[str, Any]:
        return getattr(self.raw, "messages", {})

    @property
    def mavlink(self) -> Any:
        """MAVLink constants and base message classes from the loaded dialect."""
        return self._load_mavutil().mavlink

    @property
    def sent_messages(self) -> int:
        with self._send_lock:
            return self._sent_messages

    def start(self) -> None:
        self.connect()

    def connect(self) -> None:
        with self._lifecycle_lock:
            if self._connection is not None:
                return
            connection: Any | None = None
            try:
                connection = self._create_connection()
                heartbeat = self._wait_vehicle_heartbeat(connection)
                if heartbeat is None:
                    raise TimeoutError("MAVLink heartbeat zaman aşımı")
            except Exception as exc:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception as close_error:
                        self._publish_error(close_error)
                self._publish_error(exc)
                raise
            self._connection = connection
        self.connection_changed.publish(True)

    def _wait_vehicle_heartbeat(self, connection: Any) -> Any:
        """Wait for the autopilot without accepting companion or GCS heartbeats."""
        deadline = time.monotonic() + self.endpoint.heartbeat_timeout
        classifier = getattr(connection, "probably_vehicle_heartbeat", None)
        requires_probe = self.endpoint.uri.lower().startswith("udpout:")
        next_probe = 0.0
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                raise TimeoutError("MAVLink uçuş cihazı heartbeat zaman aşımı")

            if requires_probe and now >= next_probe:
                self._send_discovery_heartbeat(connection)
                next_probe = now + self.UDP_DISCOVERY_INTERVAL_S

            wait_timeout = remaining
            if requires_probe:
                wait_timeout = min(
                    remaining,
                    max(0.01, next_probe - time.monotonic()),
                )
            heartbeat = connection.wait_heartbeat(timeout=wait_timeout)
            if heartbeat is None:
                if requires_probe:
                    continue
                raise TimeoutError("MAVLink uçuş cihazı heartbeat zaman aşımı")
            if not callable(classifier) or classifier(heartbeat):
                return heartbeat

    def _send_discovery_heartbeat(self, connection: Any) -> None:
        """Advertise the GCS endpoint so a UDP server can route telemetry back."""

        mavlink = self._load_mavutil().mavlink
        connection.mav.heartbeat_send(
            mavlink.MAV_TYPE_GCS,
            mavlink.MAV_AUTOPILOT_INVALID,
            0,
            0,
            mavlink.MAV_STATE_ACTIVE,
        )
        self._sent_messages += 1

    def reconnect(self) -> None:
        self.stop()
        self.start()

    def receive(
        self,
        *,
        message_types: MessageTypeInput | None = None,
        condition: str | None = None,
        blocking: bool = False,
        timeout: float | None = None,
    ) -> Any | None:
        """Expose pymavlink ``recv_match`` type and condition filters directly.

        Do not call this directly while the router is running; the router must
        remain the only reader.
        """
        normalized_types = normalize_message_types(message_types)
        native_types: str | list[str] | None
        if normalized_types is None:
            native_types = None
        elif len(normalized_types) == 1:
            native_types = next(iter(normalized_types))
        else:
            native_types = sorted(normalized_types)
        normalized_condition = condition.strip() if condition else None
        kwargs: dict[str, Any] = {"blocking": blocking, "timeout": timeout}
        if native_types is not None:
            kwargs["type"] = native_types
        if normalized_condition:
            kwargs["condition"] = normalized_condition
        try:
            with self._receive_lock:
                return self.raw.recv_match(**kwargs)
        except Exception as exc:
            self._publish_error(exc)
            raise

    def evaluate_condition(self, condition: str) -> bool:
        normalized = condition.strip()
        if not normalized:
            raise ValueError("MAVLink condition boş olamaz")
        mavutil = self._load_mavutil()
        return bool(mavutil.evaluate_condition(normalized, self.message_state))

    def send(self, message: Any) -> None:
        self.call_mav("send", message)

    def send_named(self, message_name: str, **parameters: Any) -> None:
        self.call_mav(f"{message_name.strip().lower()}_send", **parameters)

    def request_message_rate(
        self,
        message_id: int,
        frequency_hz: float,
        *,
        target_system: int | None = None,
        target_component: int | None = None,
    ) -> int:
        """Send the standard command requesting a MAVLink message rate.

        The return value is the period sent to the flight controller in
        microseconds. Sending is thread-safe; the vehicle layer can monitor
        command acceptance.
        """

        normalized_message_id = int(message_id)
        normalized_frequency = float(frequency_hz)
        if normalized_message_id < 0:
            raise ValueError("MAVLink mesaj kimliği negatif olamaz")
        if not 0.01 <= normalized_frequency <= 1_000.0:
            raise ValueError("MAVLink mesaj frekansı 0.01..1000 Hz aralığında olmalı")
        interval_us = max(1, round(1_000_000.0 / normalized_frequency))
        mavlink = self.mavlink
        command = int(getattr(mavlink, "MAV_CMD_SET_MESSAGE_INTERVAL", 511))
        self.call_mav(
            "command_long_send",
            self.target_system if target_system is None else int(target_system),
            self.target_component
            if target_component is None
            else int(target_component),
            command,
            0,
            float(normalized_message_id),
            float(interval_us),
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )
        return interval_us

    def call_mav(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Serialize every pymavlink ``raw.mav.*`` write through one lock."""
        try:
            with self._send_lock:
                sender_name = method_name.strip()
                sender = getattr(self.raw.mav, sender_name, None)
                if not callable(sender):
                    raise ValueError(f"Bilinmeyen MAVLink gönderim metodu: {method_name}")
                result = sender(*args, **kwargs)
                self._sent_messages += 1
                return result
        except Exception as exc:
            self._publish_error(exc)
            raise

    def call_raw(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Serialize writes outside the mav object, such as ``set_mode``."""
        try:
            with self._send_lock:
                method = getattr(self.raw, method_name.strip(), None)
                if not callable(method):
                    raise ValueError(f"Bilinmeyen pymavlink metodu: {method_name}")
                result = method(*args, **kwargs)
                self._sent_messages += 1
                return result
        except Exception as exc:
            self._publish_error(exc)
            raise

    def stop(self) -> None:
        with self._send_lock, self._receive_lock, self._lifecycle_lock:
            connection = self._connection
            self._connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception as exc:
                self._publish_error(exc)
                raise
            self.connection_changed.publish(False)

    def _create_connection(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory(self.endpoint)
        mavutil = self._load_mavutil()
        return mavutil.mavlink_connection(
            self.endpoint.uri,
            **self.endpoint.connection_kwargs(),
        )

    def _load_mavutil(self) -> Any:
        with self._lifecycle_lock:
            if self._mavutil_module is not None:
                return self._mavutil_module
            try:
                from pymavlink import mavutil
            except ImportError as exc:
                raise MavlinkUnavailableError(
                    "MAVLink kullanmak için pymavlink kurulmalı"
                ) from exc
            self._mavutil_module = mavutil
            return mavutil

    def _publish_error(self, error: Exception) -> None:
        self.errors.publish(error)

    close = stop

    def __enter__(self) -> "MavlinkConnection":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop()
