from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .filter import (
    mavlink_message_id,
    mavlink_message_type,
    mavlink_source_component,
    mavlink_source_system,
)


@dataclass(frozen=True, slots=True)
class MavlinkMessageEnvelope:
    """Once-extracted routing metadata and the raw pymavlink message."""

    sequence: int
    message: Any
    message_type: str
    source_system: int | None
    source_component: int | None
    message_id: int | None
    received_monotonic: float

    @classmethod
    def wrap(cls, sequence: int, message: Any) -> "MavlinkMessageEnvelope":
        return cls(
            sequence=sequence,
            message=message,
            message_type=mavlink_message_type(message),
            source_system=mavlink_source_system(message),
            source_component=mavlink_source_component(message),
            message_id=mavlink_message_id(message),
            received_monotonic=time.monotonic(),
        )

    def to_dict(self, *, include_payload: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sequence": self.sequence,
            "message_type": self.message_type,
            "source_system": self.source_system,
            "source_component": self.source_component,
            "message_id": self.message_id,
            "received_monotonic": self.received_monotonic,
        }
        if include_payload:
            serializer = getattr(self.message, "to_dict", None)
            payload["payload"] = serializer() if callable(serializer) else repr(self.message)
        return payload
