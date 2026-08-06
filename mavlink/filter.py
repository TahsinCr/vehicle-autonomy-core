from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, TypeAlias


MessageType: TypeAlias = str
MessageId: TypeAlias = int
# Backwards-compatible aliases used by the public client and router APIs.
MessageTypeInput: TypeAlias = MessageType | Iterable[MessageType]
MessageIdInput: TypeAlias = MessageId | Iterable[MessageId]
MessagePredicate: TypeAlias = Callable[[Any], bool]
ConditionEvaluator: TypeAlias = Callable[[str], bool]


def mavlink_message_type(message: Any) -> str:
    """Return a pymavlink message type in one normalized form."""
    getter = getattr(message, "get_type", None)
    if not callable(getter):
        raise TypeError("MAVLink mesajı get_type() sağlamalı")
    value = str(getter()).strip().upper()
    if not value:
        raise ValueError("MAVLink mesaj tipi boş olamaz")
    return value


def mavlink_source_system(message: Any) -> int | None:
    getter = getattr(message, "get_srcSystem", None)
    if callable(getter):
        value = getter()
        return int(value) if value is not None else None
    header = getattr(message, "_header", None)
    value = getattr(header, "srcSystem", None)
    return int(value) if value is not None else None


def mavlink_source_component(message: Any) -> int | None:
    getter = getattr(message, "get_srcComponent", None)
    if callable(getter):
        value = getter()
        return int(value) if value is not None else None
    header = getattr(message, "_header", None)
    value = getattr(header, "srcComponent", None)
    return int(value) if value is not None else None


def mavlink_message_id(message: Any) -> int | None:
    getter = getattr(message, "get_msgId", None)
    if not callable(getter):
        return None
    value = getter()
    return int(value) if value is not None else None


def normalize_message_types(value: MessageTypeInput | None) -> frozenset[str] | None:
    if value is None:
        return None
    values = (value,) if isinstance(value, str) else tuple(value)
    normalized = frozenset(str(item).strip().upper() for item in values if str(item).strip())
    if not normalized:
        raise ValueError("En az bir MAVLink mesaj tipi gerekli")
    return normalized


def normalize_message_ids(value: MessageIdInput | None) -> frozenset[int] | None:
    if value is None:
        return None
    values = (value,) if isinstance(value, int) else tuple(value)
    normalized = frozenset(int(item) for item in values)
    if not normalized:
        raise ValueError("En az bir MAVLink mesaj kimliği gerekli")
    if any(item < 0 for item in normalized):
        raise ValueError("MAVLink mesaj kimliği negatif olamaz")
    return normalized


def normalize_source_ids(value: int | Iterable[int] | None) -> frozenset[int] | None:
    normalized = normalize_message_ids(value)
    if normalized is not None and any(item > 255 for item in normalized):
        raise ValueError("MAVLink kaynak kimliği 0..255 aralığında olmalı")
    return normalized


@dataclass(frozen=True, slots=True)
class MavlinkMessageFilter:
    """Composite filter using MAVLink's native message metadata fields."""

    message_types: frozenset[str] | MessageTypeInput | None = None
    source_systems: frozenset[int] | int | Iterable[int] | None = None
    source_components: frozenset[int] | int | Iterable[int] | None = None
    message_ids: frozenset[int] | MessageIdInput | None = None
    condition: str | None = None
    predicate: MessagePredicate | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_types", normalize_message_types(self.message_types))
        object.__setattr__(self, "source_systems", normalize_source_ids(self.source_systems))
        object.__setattr__(self, "source_components", normalize_source_ids(self.source_components))
        object.__setattr__(self, "message_ids", normalize_message_ids(self.message_ids))
        normalized_condition = self.condition.strip() if self.condition else None
        object.__setattr__(self, "condition", normalized_condition or None)
        if self.predicate is not None and not callable(self.predicate):
            raise TypeError("MAVLink predicate callable olmalı")

    @classmethod
    def for_types(cls, *message_types: str, **criteria: Any) -> "MavlinkMessageFilter":
        return cls(message_types=message_types, **criteria)

    def matches(
        self,
        message: Any,
        *,
        condition_evaluator: ConditionEvaluator | None = None,
        metadata: Any | None = None,
    ) -> bool:
        message_type = (
            metadata.message_type if metadata is not None else mavlink_message_type(message)
        )
        source_system = (
            metadata.source_system if metadata is not None else mavlink_source_system(message)
        )
        source_component = (
            metadata.source_component
            if metadata is not None
            else mavlink_source_component(message)
        )
        message_id = metadata.message_id if metadata is not None else mavlink_message_id(message)
        if self.message_types is not None and message_type not in self.message_types:
            return False
        if self.source_systems is not None and source_system not in self.source_systems:
            return False
        if self.source_components is not None and source_component not in self.source_components:
            return False
        if self.message_ids is not None and message_id not in self.message_ids:
            return False
        if self.condition is not None:
            if condition_evaluator is None:
                raise RuntimeError("Native MAVLink condition için evaluator gerekli")
            if not condition_evaluator(self.condition):
                return False
        return self.predicate(message) if self.predicate is not None else True


def coerce_message_filter(
    value: MavlinkMessageFilter | MessageTypeInput | None,
) -> MavlinkMessageFilter:
    if isinstance(value, MavlinkMessageFilter):
        return value
    return MavlinkMessageFilter(message_types=value)
