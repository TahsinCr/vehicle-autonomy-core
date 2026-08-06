from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


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
    def get_srcSystem(self) -> int: ...
    def get_srcComponent(self) -> int: ...
    def get_seq(self) -> int: ...
    def get_msgbuf(self) -> bytearray: ...
    def to_dict(self) -> dict[str, Any]: ...
    def to_json(self) -> str: ...
