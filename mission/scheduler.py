"""Ready-to-use mission scheduling component."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
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
    MissionNotFoundError,
    MissionRegistrationError,
)
from .models import (
    MissionChain,
    MissionChainSnapshot,
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
                registered = mission.id in self.engine._runtimes
            if not registered:
                self.engine.register(mission)
        mission_id = self.engine._mission_id(mission)
        self.engine.start()

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

    def start_chain(self, chain: MissionChain) -> MissionChainSnapshot:
        if not isinstance(chain, MissionChain):
            raise TypeError("Mission engine chains must be MissionChain instances")
        with self.engine._condition:
            current = self.engine._chains.get(chain.chain_id)
            if current is not None and current.active:
                raise MissionConflictError(
                    f"Mission chain is already active: {chain.chain_id}"
                )
            snapshot = MissionChainSnapshot(chain=chain, active=True)
            self.engine._chains[chain.chain_id] = snapshot
        self.engine._emit(
            MissionEventType.CHAIN,
            f"Mission chain started: {chain.chain_id}",
        )
        try:
            self._launch_chain_index(chain.chain_id, 0)
        except Exception as exc:
            self._mark_chain_failed(chain.chain_id, exc)
            raise
        with self.engine._condition:
            return self.engine._chains[chain.chain_id]

    def chain_snapshot(self, chain_id: str) -> MissionChainSnapshot:
        with self.engine._condition:
            try:
                return self.engine._chains[str(chain_id).strip()]
            except KeyError as exc:
                raise MissionNotFoundError(
                    f"Mission chain not found: {chain_id}"
                ) from exc

    def _scheduler_loop(self) -> None:
        while not self.engine._scheduler_stop.is_set():
            self.engine._scheduler_wake.wait(self.engine._scheduler_interval)
            self.engine._scheduler_wake.clear()
            if self.engine._scheduler_stop.is_set():
                break
            self._promote_queued()

    def _promote_queued(self) -> None:
        now = time.time()
        with self.engine._condition:
            queued = sorted(
                (
                    runtime
                    for runtime in self.engine._runtimes.values()
                    if runtime.snapshot.phase is MissionPhase.QUEUED
                ),
                key=lambda item: (
                    item.mission.priority,
                    item.snapshot.queued_at or item.snapshot.registered_at,
                ),
            )
        for runtime in queued:
            snapshot = runtime.snapshot
            queue_timeout = runtime.mission.queue_timeout_seconds
            if (
                queue_timeout is not None
                and snapshot.queued_at is not None
                and now - snapshot.queued_at >= queue_timeout
            ):
                self.engine.fail(runtime.mission.id, "Mission queue timed out")
                continue
            if snapshot.next_retry_at is not None and now < snapshot.next_retry_at:
                continue
            try:
                self.launch(runtime.mission.id, reason="Queued mission released")
            except MissionConflictError:
                continue

    def _after_terminal(self, mission_id: int, *, succeeded: bool) -> None:
        self.engine._scheduler_wake.set()
        with self.engine._condition:
            chain_id = self.engine._mission_chains.pop(mission_id, None)
            if chain_id is not None and not self.engine._running:
                chain = self.engine._chains.get(chain_id)
                if chain is not None and chain.active:
                    self.engine._chains[chain_id] = replace(
                        chain,
                        active=False,
                        failed=True,
                        reason="Mission engine stopped",
                    )
                chain_id = None
        if chain_id is not None:
            self._advance_chain(chain_id, succeeded=succeeded)

    def _launch_chain_index(self, chain_id: str, index: int) -> None:
        with self.engine._condition:
            snapshot = self.engine._chains[chain_id]
            mission_type = snapshot.chain.mission_types[index]
        mission = self.engine._mission_factory(mission_type)
        if not isinstance(mission, mission_type):
            raise MissionRegistrationError(
                "Mission factory must return an instance of the requested type"
            )
        self.engine.register(mission)
        with self.engine._condition:
            self.engine._mission_chains[mission.id] = chain_id
        self.launch(mission)

    def _advance_chain(self, chain_id: str, *, succeeded: bool) -> None:
        event_message: str | None = None
        with self.engine._condition:
            snapshot = self.engine._chains.get(chain_id)
            if snapshot is None or not snapshot.active:
                return
            if not succeeded and snapshot.chain.stop_on_failure:
                self.engine._chains[chain_id] = replace(
                    snapshot,
                    active=False,
                    failed=True,
                    reason="Mission in chain failed",
                )
                event_message = f"Mission chain failed: {chain_id}"
                next_index = None
            else:
                next_index = snapshot.current_index + 1
            if (
                next_index is not None
                and next_index >= len(snapshot.chain.mission_types)
            ):
                self.engine._chains[chain_id] = replace(
                    snapshot,
                    current_index=next_index,
                    active=False,
                    completed=True,
                )
                event_message = f"Mission chain completed: {chain_id}"
                next_index = None
            elif next_index is not None:
                self.engine._chains[chain_id] = replace(
                    snapshot, current_index=next_index
                )
        if event_message is not None:
            self.engine._emit(MissionEventType.CHAIN, event_message)
        if next_index is None:
            return
        try:
            self._launch_chain_index(chain_id, next_index)
        except Exception as exc:
            self._mark_chain_failed(chain_id, exc)

    def _mark_chain_failed(self, chain_id: str, error: Exception) -> None:
        reason = f"Mission chain could not continue: {error}"
        with self.engine._condition:
            snapshot = self.engine._chains.get(chain_id)
            if snapshot is None or not snapshot.active:
                return
            self.engine._chains[chain_id] = replace(
                snapshot,
                active=False,
                failed=True,
                reason=reason,
            )
            orphaned_ids = tuple(
                mission_id
                for mission_id, owner_chain_id in self.engine._mission_chains.items()
                if owner_chain_id == chain_id
                and not self.engine._runtimes[mission_id].snapshot.phase.active
            )
            for mission_id in orphaned_ids:
                self.engine._mission_chains.pop(mission_id, None)
        self.engine._emit(
            MissionEventType.CHAIN,
            reason,
        )

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
