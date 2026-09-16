from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TypeAlias, TypedDict, runtime_checkable


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = (
    JsonScalar
    | list["JsonValue"]
    | tuple["JsonValue", ...]
    | Mapping[str, "JsonValue"]
)


class MavlinkRouterOptions(TypedDict, total=False):
    """Optional settings accepted when a runtime constructs its router."""

    history_limit: int
    cache_per_type: int
    poll_timeout: float
    error_backoff: float
    stop_timeout: float
    state_capacity: int | None
    source_capacity: int | None


class MavlinkApplicationChannelOptions(TypedDict, total=False):
    """Optional settings used to construct an application channel."""

    network_id: int
    message_type: int
    target_system: int
    target_component: int
    local_system: int | None
    local_component: int | None
    source_systems: int | tuple[int, ...] | None
    source_components: int | tuple[int, ...] | None
    fragment_timeout: float
    max_inflight_assemblies: int
    max_inflight_bytes: int
    max_completed_packets: int


class MavlinkApplicationPeerOptions(TypedDict, total=False):
    """Optional settings used to construct an application peer."""

    heartbeat_interval: float
    heartbeat_timeout: float
    stop_timeout: float


@runtime_checkable
class MavlinkHeader(Protocol):
    """Required fields from a pymavlink MAVLink message header."""

    msgId: int
    seq: int
    srcSystem: int
    srcComponent: int


@runtime_checkable
class MavlinkMessage(Protocol):
    """Dialect-independent base pymavlink message contract."""

    id: int
    msgname: str
    fieldnames: list[str]

    def get_header(self) -> MavlinkHeader: ...
    def get_type(self) -> str: ...
    def get_msgId(self) -> int: ...
    def get_srcSystem(self) -> int | None: ...
    def get_srcComponent(self) -> int | None: ...
    def get_seq(self) -> int: ...
    def get_msgbuf(self) -> bytearray: ...
    def to_dict(self) -> dict[str, JsonValue]: ...
    def to_json(self) -> str: ...


class TargetedMavlinkMessage(MavlinkMessage, Protocol):
    """A mutable outbound message carrying target addressing fields."""

    target_system: int
    target_component: int


class MavlinkV2ExtensionMessage(MavlinkMessage, Protocol):
    """Fields consumed from the MAVLink ``V2_EXTENSION`` message."""

    target_network: int
    target_system: int
    target_component: int
    message_type: int
    payload: bytes | bytearray | list[int] | tuple[int, ...]


class MavlinkMessageMetadata(Protocol):
    """Pre-extracted message fields consumed by routing filters."""

    message_type: str
    source_system: int | None
    source_component: int | None
    message_id: int | None


class MavlinkSender(Protocol):
    """Dynamic ``connection.mav`` sender surface used by pymavlink."""

    def send(self, message: MavlinkMessage) -> object: ...
    def heartbeat_send(
        self,
        vehicle_type: int,
        autopilot: int,
        base_mode: int,
        custom_mode: int,
        system_status: int,
    ) -> object: ...


class MavlinkConnectionBackend(Protocol):
    """Subset of a pymavlink connection required by the core."""

    mav: MavlinkSender
    messages: Mapping[str, MavlinkMessage]
    target_system: int
    target_component: int

    def wait_heartbeat(self, *, timeout: float) -> MavlinkMessage | None: ...
    def recv_match(self, **options: object) -> MavlinkMessage | None: ...
    def probably_vehicle_heartbeat(self, message: MavlinkMessage) -> bool: ...
    def close(self) -> None: ...


class MavlinkDialect(Protocol):
    """Known constants exposed by a loaded pymavlink dialect."""

    MAV_TYPE_GCS: int
    MAV_AUTOPILOT_INVALID: int
    MAV_STATE_ACTIVE: int
    MAV_CMD_SET_MESSAGE_INTERVAL: int


class MavutilModule(Protocol):
    """Import-safe pymavlink module contract used by ``MavlinkConnection``."""

    mavlink: MavlinkDialect

    def mavlink_connection(
        self, endpoint: str, **options: object
    ) -> MavlinkConnectionBackend: ...

    def evaluate_condition(
        self,
        condition: str,
        messages: Mapping[str, MavlinkMessage],
    ) -> object: ...
