from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from ..compatibility import StrEnum
from typing import Any

REMOTE_LOG_PACKET_TYPE = "logs.push"
REMOTE_LOG_PROTOCOL_VERSION = 1
REMOTE_LOG_MAX_BATCH_RECORDS = 16
REMOTE_LOG_MAX_BATCH_BYTES = 12_000
REMOTE_LOG_MAX_DETAILS_BYTES = 3_000

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{4,96}$")


class MavlinkRemoteLogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def priority(self) -> int:
        return {
            MavlinkRemoteLogLevel.DEBUG: 10,
            MavlinkRemoteLogLevel.INFO: 20,
            MavlinkRemoteLogLevel.SUCCESS: 25,
            MavlinkRemoteLogLevel.WARNING: 30,
            MavlinkRemoteLogLevel.ERROR: 40,
            MavlinkRemoteLogLevel.CRITICAL: 50,
        }[self]

@dataclass(frozen=True, slots=True)
class MavlinkRemoteLogRecord:
    """One transport-safe structured log emitted by an onboard application."""

    sequence: int
    source: str
    action: str
    message: str
    level: MavlinkRemoteLogLevel = MavlinkRemoteLogLevel.INFO
    emitted_at: float = field(default_factory=time.time)
    details: Mapping[str, Any] = field(default_factory=dict)
    device_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        sequence = int(self.sequence)
        source = str(self.source).strip().upper()
        action = str(self.action).strip().lower()
        message = str(self.message).strip()
        emitted_at = float(self.emitted_at)
        details = dict(self.details)
        if sequence <= 0:
            raise ValueError("Remote log sequence must be positive")
        if not source or len(source) > 64:
            raise ValueError("Remote log source must contain 1..64 characters")
        if not action or len(action) > 96:
            raise ValueError("Remote log action must contain 1..96 characters")
        if not message or len(message) > 1_024:
            raise ValueError("Remote log message must contain 1..1024 characters")
        if not math.isfinite(emitted_at) or emitted_at <= 0:
            raise ValueError("Remote log timestamp must be a positive finite value")
        try:
            details_json = json.dumps(
                details,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Remote log details must be JSON compatible: {exc}") from exc
        if len(details_json) > REMOTE_LOG_MAX_DETAILS_BYTES:
            raise ValueError(
                "Remote log details exceed "
                f"{REMOTE_LOG_MAX_DETAILS_BYTES} encoded bytes"
            )
        device_id = _optional_text(self.device_id, maximum=96)
        correlation_id = _optional_text(self.correlation_id, maximum=128)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "level", MavlinkRemoteLogLevel(self.level))
        object.__setattr__(self, "emitted_at", emitted_at)
        object.__setattr__(self, "details", deepcopy(details))
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "correlation_id", correlation_id)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "seq": self.sequence,
            "source": self.source,
            "action": self.action,
            "message": self.message,
            "level": self.level.value,
            "at": self.emitted_at,
            "details": deepcopy(self.details),
        }
        if self.device_id is not None:
            payload["device_id"] = self.device_id
        if self.correlation_id is not None:
            payload["correlation_id"] = self.correlation_id
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MavlinkRemoteLogRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("Remote log record payload must be an object")
        details = payload.get("details", {})
        if not isinstance(details, Mapping):
            raise ValueError("Remote log details must be an object")
        return cls(
            sequence=int(payload.get("seq", 0)),
            source=str(payload.get("source", "")),
            action=str(payload.get("action", "")),
            message=str(payload.get("message", "")),
            level=MavlinkRemoteLogLevel(str(payload.get("level", "info")).lower()),
            emitted_at=float(payload.get("at", 0.0)),
            details=dict(details),
            device_id=_payload_optional_text(payload.get("device_id")),
            correlation_id=_payload_optional_text(payload.get("correlation_id")),
        )


@dataclass(frozen=True, slots=True)
class MavlinkRemoteLogBatch:
    """An ordered log batch acknowledged as one application request."""

    session_id: str
    records: tuple[MavlinkRemoteLogRecord, ...]
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        session_id = str(self.session_id).strip()
        records = tuple(self.records)
        created_at = float(self.created_at)
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("Remote log session ID is invalid")
        if not 1 <= len(records) <= REMOTE_LOG_MAX_BATCH_RECORDS:
            raise ValueError(
                f"Remote log batch must contain 1..{REMOTE_LOG_MAX_BATCH_RECORDS} records"
            )
        if any(
            current.sequence >= following.sequence
            for current, following in zip(records, records[1:])
        ):
            raise ValueError("Remote log records must be ordered by unique sequence")
        if not math.isfinite(created_at) or created_at <= 0:
            raise ValueError("Remote log batch timestamp must be positive")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "created_at", created_at)
        payload_size = len(
            json.dumps(
                self.to_payload(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if payload_size > REMOTE_LOG_MAX_BATCH_BYTES:
            raise ValueError(
                f"Remote log batch exceeds {REMOTE_LOG_MAX_BATCH_BYTES} encoded bytes"
            )

    @property
    def first_sequence(self) -> int:
        return self.records[0].sequence

    @property
    def last_sequence(self) -> int:
        return self.records[-1].sequence

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": REMOTE_LOG_PROTOCOL_VERSION,
            "session": self.session_id,
            "created_at": self.created_at,
            "records": [record.to_payload() for record in self.records],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MavlinkRemoteLogBatch":
        if not isinstance(payload, Mapping):
            raise ValueError("Remote log batch payload must be an object")
        version = int(payload.get("version", 0))
        if version != REMOTE_LOG_PROTOCOL_VERSION:
            raise ValueError(f"Unsupported remote log protocol version: {version}")
        values = payload.get("records")
        if not isinstance(values, list):
            raise ValueError("Remote log records must be a list")
        return cls(
            session_id=str(payload.get("session", "")),
            records=tuple(
                MavlinkRemoteLogRecord.from_payload(value)
                for value in values
            ),
            created_at=float(payload.get("created_at", 0.0)),
        )


def _optional_text(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValueError(f"Remote log metadata exceeds {maximum} characters")
    return normalized


def _payload_optional_text(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "MavlinkRemoteLogBatch",
    "MavlinkRemoteLogLevel",
    "MavlinkRemoteLogRecord",
    "REMOTE_LOG_MAX_BATCH_BYTES",
    "REMOTE_LOG_MAX_BATCH_RECORDS",
    "REMOTE_LOG_MAX_DETAILS_BYTES",
    "REMOTE_LOG_PACKET_TYPE",
    "REMOTE_LOG_PROTOCOL_VERSION",
]
