"""Small internal runtime records used by the mission engine."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .controller import MissionController
from .models import MissionSnapshot

if TYPE_CHECKING:
    from .base import Mission
    from .engine import MissionEngine


@dataclass(slots=True)
class MissionRuntime:
    mission: "Mission"
    snapshot: MissionSnapshot
    stop_event: threading.Event
    control: "BoundMissionController"
    worker: threading.Thread | None = None
    cleaned: bool = False
    cleanup_lock: threading.Lock = field(default_factory=threading.Lock)
    callback_lock: threading.RLock = field(default_factory=threading.RLock)
    active_elapsed: float = 0.0
    active_started_monotonic: float | None = None


class BoundMissionController(MissionController):
    """Give one mission a safe view of the shared engine."""

    def __init__(self, engine: "MissionEngine", mission_id: int) -> None:
        self._engine = engine
        self._mission_id = mission_id

    @property
    def mission_id(self) -> int:
        return self._mission_id

    @property
    def stop_requested(self) -> bool:
        return self._engine._stop_requested(self._mission_id)

    def snapshot(self, mission_id: int | None = None) -> MissionSnapshot:
        return self._engine.snapshot(self._mission_id if mission_id is None else mission_id)

    def snapshots(self) -> tuple[MissionSnapshot, ...]:
        return self._engine.snapshots()

    def wait_for_stop(self, timeout: float | None = None) -> bool:
        return self._engine._wait_for_stop(self._mission_id, timeout)

    def start(self, mission_id: int, *, reason: str = "") -> MissionSnapshot:
        return self._engine.launch(
            mission_id,
            requester_id=self._mission_id,
            reason=reason,
        )

    def pause(self, mission_id: int, *, reason: str = "") -> MissionSnapshot:
        return self._engine.pause(
            mission_id,
            requester_id=self._mission_id,
            reason=reason,
        )

    def resume(self, mission_id: int, *, reason: str = "") -> MissionSnapshot:
        return self._engine.resume(
            mission_id,
            requester_id=self._mission_id,
            reason=reason,
        )

    def stop(self, mission_id: int, *, reason: str = "") -> MissionSnapshot:
        return self._engine.stop_mission(
            mission_id,
            requester_id=self._mission_id,
            reason=reason,
        )

    def cancel(self, mission_id: int, *, reason: str = "") -> MissionSnapshot:
        return self._engine.cancel(
            mission_id,
            requester_id=self._mission_id,
            reason=reason,
        )

    def stop_matching(
        self,
        *,
        tags: Iterable[str] = (),
        resources: Iterable[str] = (),
    ) -> tuple[MissionSnapshot, ...]:
        return self._engine.stop_matching(
            self._mission_id,
            tags=tags,
            resources=resources,
        )

    def complete(
        self,
        result: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot:
        return self._engine.complete(self._mission_id, result)

    def fail(self, reason: str, *, retryable: bool = False) -> MissionSnapshot:
        return self._engine.fail(
            self._mission_id,
            reason,
            retryable=retryable,
        )

    def progress(self, value: float, *, reason: str = "") -> MissionSnapshot:
        return self._engine.progress(self._mission_id, value, reason=reason)

    def checkpoint(
        self,
        name: str,
        values: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot:
        return self._engine.checkpoint(self._mission_id, name, values)
