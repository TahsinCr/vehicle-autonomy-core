from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..abstracts import Service
from ..events import Subscription
from .connection import MavlinkConnection
from .endpoint import MavlinkEndpoint
from .filter import MessagePredicate, MessageTypeInput, MavlinkMessageFilter
from .router import MavlinkMessageRouter


class MavlinkClient(Service):
    """Combine connection and router lifecycles behind one modular interface."""

    def __init__(
        self,
        endpoint: MavlinkEndpoint | None = None,
        *,
        connection: MavlinkConnection | None = None,
        router: MavlinkMessageRouter | None = None,
    ) -> None:
        if connection is None and router is not None:
            connection = router.connection
        if connection is None:
            connection = MavlinkConnection(endpoint or MavlinkEndpoint())
        elif endpoint is not None and connection.endpoint != endpoint:
            raise ValueError("MavlinkClient endpoint ve connection endpoint uyuşmuyor")
        if router is not None and router.connection is not connection:
            raise ValueError("MavlinkClient router farklı bir connection kullanıyor")
        self.connection = connection
        self.router = router or MavlinkMessageRouter(connection)

    @property
    def endpoint(self) -> MavlinkEndpoint:
        return self.connection.endpoint

    @property
    def raw(self) -> Any:
        return self.connection.raw

    @property
    def is_connected(self) -> bool:
        return self.connection.is_connected

    @property
    def mavlink(self) -> Any:
        return self.connection.mavlink

    def start(self) -> None:
        self.router.start()

    def stop(self) -> None:
        self.router.stop()

    def configure_endpoint(self, endpoint: MavlinkEndpoint) -> None:
        """Change transport settings of a closed client for its next connection."""
        if self.router.running or self.connection.is_connected:
            raise RuntimeError("Çalışan MAVLink istemcisi yeniden yapılandırılamaz")
        self.connection.endpoint = endpoint

    close = stop

    def subscribe(
        self,
        callback: Callable[[Any], None],
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
    ) -> Subscription:
        return self.router.subscribe(callback, message_filter)

    def wait_for(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        *,
        predicate: MessagePredicate | None = None,
        timeout: float = 3.0,
        after_sequence: int | None = None,
    ) -> Any:
        return self.router.wait_for(
            message_types,
            predicate=predicate,
            timeout=timeout,
            after_sequence=after_sequence,
        )

    def latest(
        self,
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
    ) -> Any | None:
        return self.router.latest(message_filter)

    def send(self, message: Any) -> None:
        self.connection.send(message)

    def send_named(self, message_name: str, **parameters: Any) -> None:
        self.connection.send_named(message_name, **parameters)

    def request_message_rate(
        self,
        message_id: int,
        frequency_hz: float,
        *,
        target_system: int | None = None,
        target_component: int | None = None,
    ) -> int:
        return self.connection.request_message_rate(
            message_id,
            frequency_hz,
            target_system=target_system,
            target_component=target_component,
        )

    def call_mav(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        return self.connection.call_mav(method_name, *args, **kwargs)

    def call_raw(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        return self.connection.call_raw(method_name, *args, **kwargs)

    def __enter__(self) -> "MavlinkClient":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop()
