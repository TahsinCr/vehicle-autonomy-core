"""Ready-to-use mission scheduling component."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from .base import Mission
from .enums import (
    MissionConflictPolicy,
    MissionPhase,
    MissionPrerequisitePolicy,
)
from .errors import (
    MissionConflictError,
    MissionRegistrationError,
)
from .models import (
    MissionSnapshot,
    MissionTransition,
)
from .runtime import MissionRuntime

if TYPE_CHECKING:
    from .engine import MissionEngine


MissionReference = Mission | int


class MissionScheduler:
    """Schedule missions for one engine using queues and declared policies.

    The default instance is created by ``MissionEngine``. Passing a subclass
    instance to the engine provides a direct extension point for scheduling
    rules without relying on multiple inheritance.
    """

    def __init__(self, engine: "MissionEngine | None" = None) -> None:
        self._engine: MissionEngine | None = None
        if engine is not None:
            self.bind(engine)

    @property
    def engine(self) -> "MissionEngine":
        if self._engine is None:
            raise RuntimeError("Mission scheduler is not bound to an engine")
        return self._engine

    def bind(self, engine: "MissionEngine") -> "MissionScheduler":
        """Bind this scheduler to one engine; repeated binding is idempotent."""

        from .engine import MissionEngine

        if not isinstance(engine, MissionEngine):
            raise TypeError("Mission scheduler requires a MissionEngine")
        if self._engine is not None and self._engine is not engine:
            raise RuntimeError("Mission scheduler is already bound to another engine")
        self._engine = engine
        return self

    def launch(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        """Register when needed and start or queue one mission."""

        if isinstance(mission, Mission):
            with self.engine._condition:
                registered = self.engine._runtimes.get(mission.id)
            if registered is not None and registered.mission is not mission:
                raise MissionRegistrationError(
                    f"Mission {mission.id} is already registered"
                )
            if registered is None:
                try:
                    self.engine.register(mission)
                except MissionRegistrationError:
                    with self.engine._condition:
                        runtime = self.engine._runtimes.get(mission.id)
                        if runtime is None or runtime.mission is not mission:
                            raise
        mission_id = self.engine._mission_id(mission)
        self.engine.start()
        runtime = self.engine._runtime(mission_id)
        with runtime.launch_lock:
            return self._launch_serialized(
                mission_id,
                requester_id=requester_id,
                reason=reason,
            )

    def _launch_serialized(
        self,
        mission_id: int,
        *,
        requester_id: int | None,
        reason: str,
    ) -> MissionSnapshot:
        """Perform one launch while holding the mission's launch lock."""

        preempt_ids: tuple[int, ...] = ()
        queued: tuple[MissionSnapshot, MissionTransition | None] | None = None
        with self.engine._condition:
            runtime = self.engine._runtime_locked(mission_id)
            self.engine._authorize_locked(requester_id, runtime)
            if runtime.snapshot.phase.active:
                return runtime.snapshot
            missing = self._missing_prerequisites_locked(runtime.mission)
            conflicts = self._conflicts_locked(runtime.mission)
            if missing:
                if (
                    runtime.mission.prerequisite_policy
                    is MissionPrerequisitePolicy.QUEUE
                ):
                    queued = self.engine.lifecycle._queue_locked(
                        runtime,
                        reason or "Waiting for prerequisites",
                    )
                else:
                    names = ", ".join(item.__name__ for item in missing)
                    raise MissionConflictError(
                        f"Missing mission prerequisites: {names}"
                    )
            elif conflicts:
                policy = runtime.mission.conflict_policy
                if policy is MissionConflictPolicy.QUEUE:
                    queued = self.engine.lifecycle._queue_locked(
                        runtime,
                        reason or "Waiting for resources",
                    )
                elif policy is MissionConflictPolicy.PREEMPT_LOWER:
                    lower = tuple(
                        item
                        for item in conflicts
                        if runtime.mission.priority < item.mission.priority
                    )
                    if len(lower) != len(conflicts):
                        raise MissionConflictError(
                            "Mission cannot preempt an equal or "
                            "higher-priority conflict"
                        )
                    preempt_ids = tuple(item.mission.id for item in lower)
                else:
                    raise MissionConflictError(
                        self.engine._conflict_message(runtime, conflicts)
                    )

        if queued is not None:
            snapshot, transition = queued
            self.engine.lifecycle._publish_transition(transition)
            return snapshot

        for conflict_id in preempt_ids:
            self.engine.stop_mission(
                conflict_id,
                requester_id=mission_id,
                reason=f"Preempted by {runtime.mission.name}",
            )

        queued = None
        with self.engine._condition:
            runtime = self.engine._runtime_locked(mission_id)
            conflicts = self._conflicts_locked(runtime.mission)
            if conflicts:
                queued = self.engine.lifecycle._queue_locked(
                    runtime,
                    reason or "Waiting for resources",
                )
            else:
                runtime.stop_event.clear()
                runtime.cleaned = False
                snapshot, transition = self.engine.lifecycle._transition_locked(
                    runtime,
                    MissionPhase.STARTING,
                    reason=reason,
                    requester_id=requester_id,
                )
                generation = snapshot.generation
        if queued is not None:
            snapshot, transition = queued
        self.engine.lifecycle._publish_transition(transition)
        if queued is None:
            with self.engine._condition:
                runtime = self.engine._runtime_locked(mission_id)
                if (
                    runtime.snapshot.generation == generation
                    and runtime.snapshot.phase is MissionPhase.STARTING
                ):
                    worker = threading.Thread(
                        target=self.engine.lifecycle._run_mission,
                        args=(mission_id, generation),
                        name=f"Mission[{runtime.mission.name}:{mission_id}]",
                        daemon=True,
                    )
                    runtime.worker = worker
                    worker.start()
                snapshot = runtime.snapshot
        return snapshot

    def run(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.launch(
            mission,
            requester_id=requester_id,
            reason=reason,
        )

    def launch_many(self, *missions: MissionReference) -> tuple[MissionSnapshot, ...]:
        """Launch independent missions; non-conflicting work runs in parallel."""

        return tuple(self.launch(mission) for mission in missions)

    def run_parallel(
        self,
        *missions: MissionReference,
    ) -> tuple[MissionSnapshot, ...]:
        return self.launch_many(*missions)

    def _scheduler_loop(self) -> None:
        while not self.engine._scheduler_stop.is_set():
            self.engine._scheduler_wake.wait(self.engine._scheduler_interval)
            self.engine._scheduler_wake.clear()
            if self.engine._scheduler_stop.is_set():
                break
            self._promote_queued()

    def _promote_queued(self) -> None:
        now = time.time()
        monotonic_now = time.monotonic()
        with self.engine._condition:
            queued = sorted(
                (
                    (
                        runtime.mission.id,
                        runtime.snapshot.generation,
                        runtime.queued_monotonic,
                        runtime.mission.priority,
                    )
                    for runtime in self.engine._runtimes.values()
                    if runtime.snapshot.phase is MissionPhase.QUEUED
                ),
                key=lambda item: (
                    item[3],
                    item[2] if item[2] is not None else float("inf"),
                ),
            )
        for mission_id, generation, queued_at, _priority in queued:
            transition: MissionTransition | None = None
            with self.engine._condition:
                runtime = self.engine._runtimes.get(mission_id)
                if (
                    runtime is None
                    or runtime.snapshot.phase is not MissionPhase.QUEUED
                    or runtime.snapshot.generation != generation
                    or runtime.queued_monotonic != queued_at
                ):
                    continue
                snapshot = runtime.snapshot
                queue_timeout = runtime.mission.queue_timeout_seconds
                if (
                    queue_timeout is not None
                    and queued_at is not None
                    and monotonic_now - queued_at >= queue_timeout
                ):
                    snapshot, transition = self.engine.lifecycle._transition_locked(
                        runtime,
                        MissionPhase.FAILED,
                        reason="Mission queue timed out",
                    )
            if transition is not None:
                self.engine.lifecycle._publish_transition(transition)
                self._after_terminal(mission_id, succeeded=False)
                continue
            if snapshot.next_retry_at is not None and now < snapshot.next_retry_at:
                continue
            try:
                self.launch(mission_id, reason="Queued mission released")
            except MissionConflictError:
                continue

    def _after_terminal(self, mission_id: int, *, succeeded: bool) -> None:
        del succeeded
        self.engine._orchestrator.after_terminal(mission_id)

    def _missing_prerequisites_locked(
        self,
        mission: Mission,
    ) -> tuple[type[Mission], ...]:
        succeeded_types = {
            type(runtime.mission)
            for runtime in self.engine._runtimes.values()
            if runtime.snapshot.phase is MissionPhase.SUCCEEDED
        }
        return tuple(
            requirement
            for requirement in mission.prerequisites
            if not any(
                issubclass(succeeded_type, requirement)
                for succeeded_type in succeeded_types
            )
        )

    def _conflicts_locked(self, mission: Mission) -> tuple[MissionRuntime, ...]:
        conflicts: list[MissionRuntime] = []
        for runtime in self.engine._runtimes.values():
            other = runtime.mission
            if other.id == mission.id or not runtime.snapshot.phase.active:
                continue
            resource_conflict = bool(mission.resources & other.resources)
            type_conflict = any(
                isinstance(other, blocked) for blocked in mission.blocks
            )
            reverse_conflict = any(
                isinstance(mission, blocked) for blocked in other.blocks
            )
            if resource_conflict or type_conflict or reverse_conflict:
                conflicts.append(runtime)
        return tuple(conflicts)
