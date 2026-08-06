"""Mission snapshots, events, retry policies, and chains."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from ..abstracts import Model
from .enums import (
    MissionEventLevel,
    MissionEventType,
    MissionPhase,
)

if TYPE_CHECKING:
    from .base import Mission


@dataclass(frozen=True, slots=True)
class MissionRetryPolicy(Model):
    attempts: int = 1
    delay: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise ValueError("Mission retry attempts must be an integer")
        if self.attempts < 1:
            raise ValueError("Mission retry attempts must be at least one")
        delay = float(self.delay)
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Mission retry delay must be finite and non-negative")
        object.__setattr__(self, "delay", delay)


@dataclass(frozen=True, slots=True)
class MissionSnapshot(Model):
    mission_id: int
    name: str
    phase: MissionPhase = MissionPhase.REGISTERED
    generation: int = 0
    attempt: int = 0
    progress: float = 0.0
    reason: str = ""
    result: Mapping[str, Any] = field(default_factory=dict)
    checkpoints: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    queued_at: float | None = None
    next_retry_at: float | None = None
    started_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def __post_init__(self) -> None:
        if self.mission_id <= 0:
            raise ValueError("Mission ID must be positive")
        name = str(self.name).strip()
        if not name:
            raise ValueError("Mission name cannot be empty")
        if self.generation < 0 or self.attempt < 0:
            raise ValueError("Mission generation and attempt cannot be negative")
        if not 0.0 <= float(self.progress) <= 1.0:
            raise ValueError("Mission progress must be between zero and one")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "phase", MissionPhase(self.phase))
        object.__setattr__(self, "progress", float(self.progress))
        object.__setattr__(self, "result", deepcopy(dict(self.result)))
        object.__setattr__(
            self,
            "checkpoints",
            {
                str(name): deepcopy(dict(value))
                for name, value in self.checkpoints.items()
            },
        )

    def evolve(self, **changes: Any) -> "MissionSnapshot":
        changes.setdefault("updated_at", time.time())
        return replace(self, **changes)

    @property
    def duration_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)


@dataclass(frozen=True, slots=True)
class MissionEvent(Model):
    event_type: MissionEventType
    message: str
    level: MissionEventLevel = MissionEventLevel.INFO
    mission_id: int | None = None
    requester_id: int | None = None
    generation: int = 0
    fields: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        message = str(self.message).strip()
        if not message:
            raise ValueError("Mission event message cannot be empty")
        if self.mission_id is not None and self.mission_id <= 0:
            raise ValueError("Mission ID must be positive")
        if self.requester_id is not None and self.requester_id <= 0:
            raise ValueError("Requester mission ID must be positive")
        if self.sequence < 0:
            raise ValueError("Mission event sequence cannot be negative")
        if self.generation < 0:
            raise ValueError("Mission event generation cannot be negative")
        object.__setattr__(self, "event_type", MissionEventType(self.event_type))
        object.__setattr__(self, "level", MissionEventLevel(self.level))
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "fields", deepcopy(dict(self.fields)))


@dataclass(frozen=True, slots=True)
class MissionEventQuery(Model):
    mission_ids: frozenset[int] = field(default_factory=frozenset)
    event_types: frozenset[MissionEventType] = field(default_factory=frozenset)
    minimum_level: MissionEventLevel = MissionEventLevel.DEBUG
    after_sequence: int = 0
    limit: int = 200

    def __post_init__(self) -> None:
        if self.after_sequence < 0:
            raise ValueError("Mission event cursor cannot be negative")
        if self.limit <= 0:
            raise ValueError("Mission event query limit must be positive")
        mission_ids = frozenset(int(value) for value in self.mission_ids)
        if any(value <= 0 for value in mission_ids):
            raise ValueError("Mission IDs must be positive")
        object.__setattr__(self, "mission_ids", mission_ids)
        object.__setattr__(
            self,
            "event_types",
            frozenset(MissionEventType(value) for value in self.event_types),
        )
        object.__setattr__(
            self,
            "minimum_level",
            MissionEventLevel(self.minimum_level),
        )

    def matches(self, event: MissionEvent) -> bool:
        return (
            event.sequence > self.after_sequence
            and event.level >= self.minimum_level
            and (not self.mission_ids or event.mission_id in self.mission_ids)
            and (not self.event_types or event.event_type in self.event_types)
        )


@dataclass(frozen=True, slots=True)
class MissionManagerSnapshot(Model):
    running: bool = False
    registered_missions: tuple[int, ...] = ()
    active_missions: tuple[int, ...] = ()
    queued_missions: tuple[int, ...] = ()
    paused_missions: tuple[int, ...] = ()
    resource_owners: Mapping[str, int] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_owners", dict(self.resource_owners))


@dataclass(frozen=True, slots=True)
class MissionTransition(Model):
    mission_id: int
    previous: MissionPhase
    current: MissionPhase
    requester_id: int | None
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class MissionChain(Model):
    chain_id: str
    mission_types: tuple[type["Mission"], ...]
    stop_on_failure: bool = True

    def __post_init__(self) -> None:
        from .base import Mission

        chain_id = str(self.chain_id).strip()
        if not chain_id:
            raise ValueError("Mission chain ID cannot be empty")
        if not self.mission_types:
            raise ValueError("Mission chain must contain at least one mission")
        if any(
            not isinstance(mission_type, type)
            or not issubclass(mission_type, Mission)
            for mission_type in self.mission_types
        ):
            raise ValueError("Mission chain entries must be Mission subclasses")
        object.__setattr__(self, "chain_id", chain_id)


@dataclass(frozen=True, slots=True)
class MissionChainSnapshot(Model):
    chain: MissionChain
    current_index: int = 0
    active: bool = False
    completed: bool = False
    failed: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if self.current_index < 0:
            raise ValueError("Mission chain index cannot be negative")

    @property
    def current_mission_type(self) -> type["Mission"] | None:
        if not self.active or self.current_index >= len(self.chain.mission_types):
            return None
        return self.chain.mission_types[self.current_index]
