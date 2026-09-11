"""Ready-to-use mission scheduling component."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from .base import Mission
from .enums import (
    MissionConflictPolicy,
    MissionEventType,
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


class SchedulerWake:
    """Generation-based wake signal that cannot lose concurrent notifications."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._condition:
            return self._generation

    def set(self) -> None:
        with self._condition:
            self._generation += 1
            self._condition.notify_all()

    def wait(self, generation: int, timeout: float) -> int:
        with self._condition:
            self._condition.wait_for(
                lambda: self._generation != generation,
                timeout,
            )
            return self._generation


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

        self.engine._ensure_launchable()
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
            at_capacity = self._at_active_capacity_locked()
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
            elif at_capacity:
                queued = self.engine.lifecycle._queue_locked(
                    runtime,
                    reason or "Waiting for mission capacity",
                )

        if queued is not None:
            snapshot, transition = queued
            self.engine.lifecycle._publish_transition(transition)
            return snapshot

        for conflict_id in preempt_ids:
            self.engine.stop_mission(
                conflict_id,
                reason=f"Preempted by {runtime.mission.name}",
            )

        queued = None
        retry_preempt_ids: tuple[int, ...] = ()
        with self.engine._condition:
            runtime = self.engine._runtime_locked(mission_id)
            missing = self._missing_prerequisites_locked(runtime.mission)
            conflicts = self._conflicts_locked(runtime.mission)
            if missing:
                if runtime.mission.prerequisite_policy is MissionPrerequisitePolicy.QUEUE:
                    queued = self.engine.lifecycle._queue_locked(
                        runtime, reason or "Waiting for prerequisites"
                    )
                else:
                    names = ", ".join(item.__name__ for item in missing)
                    raise MissionConflictError(
                        f"Missing mission prerequisites: {names}"
                    )
            elif self._at_active_capacity_locked():
                queued = self.engine.lifecycle._queue_locked(
                    runtime,
                    reason or "Waiting for mission capacity",
                )
            elif conflicts:
                policy = runtime.mission.conflict_policy
                if policy is MissionConflictPolicy.QUEUE:
                    queued = self.engine.lifecycle._queue_locked(
                        runtime, reason or "Waiting for resources"
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
                    retry_preempt_ids = tuple(item.mission.id for item in lower)
                else:
                    raise MissionConflictError(
                        self.engine._conflict_message(runtime, conflicts)
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
        if retry_preempt_ids:
            for conflict_id in retry_preempt_ids:
                self.engine.stop_mission(
                    conflict_id,
                    reason=f"Preempted by {runtime.mission.name}",
                )
            return self._launch_serialized(
                mission_id,
                requester_id=requester_id,
                reason=reason,
            )
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
        generation = self.engine._scheduler_wake.generation
        while not self.engine._scheduler_stop.is_set():
            generation = self.engine._scheduler_wake.wait(
                generation,
                self.engine._scheduler_interval,
            )
            if self.engine._scheduler_stop.is_set():
                break
            self._expire_timeouts()
            self._promote_queued()

    def _expire_timeouts(self) -> None:
        now = time.monotonic()
        with self.engine._condition:
            expired = tuple(
                mission_id
                for mission_id in self.engine._active_ids
                if self._timed_out_locked(
                    self.engine._runtime_locked(mission_id),
                    now,
                )
            )
        for mission_id in expired:
            try:
                self.engine.fail(
                    mission_id,
                    "Mission execution timed out",
                    retryable=True,
                )
            except Exception as exc:
                self.engine._emit(
                    MissionEventType.ERROR,
                    f"Mission timeout cleanup failed: {exc}",
                    mission_id=mission_id,
                )

    @staticmethod
    def _timed_out_locked(runtime: MissionRuntime, now: float) -> bool:
        timeout = runtime.mission.timeout_seconds
        if timeout is None or runtime.snapshot.phase is MissionPhase.STOPPING:
            return False
        if runtime.snapshot.phase is MissionPhase.STARTING:
            started = runtime.attempt_started_monotonic
            return started is not None and now - started >= timeout
        if runtime.snapshot.phase is not MissionPhase.RUNNING:
            return False
        elapsed = runtime.active_elapsed
        if runtime.active_started_monotonic is not None:
            elapsed += max(0.0, now - runtime.active_started_monotonic)
        return elapsed >= timeout

    def _promote_queued(self) -> None:
        now = time.monotonic()
        with self.engine._condition:
            queued = sorted(
                (
                    (
                        runtime.mission.id,
                        runtime.snapshot.generation,
                        runtime.queued_monotonic,
                        runtime.mission.priority,
                    )
                    for mission_id in self.engine._queued_ids
                    for runtime in (self.engine._runtime_locked(mission_id),)
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
                    and now - queued_at >= queue_timeout
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
            if (
                runtime.next_retry_monotonic is not None
                and now < runtime.next_retry_monotonic
            ):
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
        succeeded_types = tuple(self.engine._succeeded_type_counts)
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
        resource_ids: set[int] = set()
        for resource in mission.resources:
            resource_ids.update(self.engine._resource_owners.get(resource, ()))
        candidate_ids = (
            self.engine._active_ids
            if mission.blocks or any(
                self.engine._runtime_locked(item).mission.blocks
                for item in self.engine._active_ids
            )
            else resource_ids
        )
        for mission_id in candidate_ids:
            runtime = self.engine._runtime_locked(mission_id)
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

    def _at_active_capacity_locked(self) -> bool:
        limit = self.engine._max_active_missions
        return limit is not None and len(self.engine._active_ids) >= limit
