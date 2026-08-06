"""Mission launch, queue, retry, conflict, and chain scheduling."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

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
from .models import MissionChain, MissionChainSnapshot, MissionSnapshot
from .runtime import MissionRuntime


MissionReference = Mission | int


class MissionSchedulingMixin:
    def launch(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        """Register when needed and start or queue one mission."""

        if isinstance(mission, Mission):
            with self._condition:
                registered = mission.id in self._runtimes
            if not registered:
                self.register(mission)
        mission_id = self._mission_id(mission)
        self.start()

        preempt_ids: tuple[int, ...] = ()
        with self._condition:
            runtime = self._runtime_locked(mission_id)
            self._authorize_locked(requester_id, runtime)
            if runtime.snapshot.phase.active:
                return runtime.snapshot
            missing = self._missing_prerequisites_locked(runtime.mission)
            conflicts = self._conflicts_locked(runtime.mission)
            if missing:
                if runtime.mission.prerequisite_policy is MissionPrerequisitePolicy.QUEUE:
                    return self._queue_locked(runtime, reason or "Waiting for prerequisites")
                names = ", ".join(item.__name__ for item in missing)
                raise MissionConflictError(f"Missing mission prerequisites: {names}")
            if conflicts:
                policy = runtime.mission.conflict_policy
                if policy is MissionConflictPolicy.QUEUE:
                    return self._queue_locked(runtime, reason or "Waiting for resources")
                if policy is MissionConflictPolicy.PREEMPT_LOWER:
                    lower = tuple(
                        item
                        for item in conflicts
                        if runtime.mission.priority < item.mission.priority
                    )
                    if len(lower) != len(conflicts):
                        raise MissionConflictError(
                            "Mission cannot preempt an equal or higher-priority conflict"
                        )
                    preempt_ids = tuple(item.mission.id for item in lower)
                else:
                    raise MissionConflictError(self._conflict_message(runtime, conflicts))

        for conflict_id in preempt_ids:
            self.stop_mission(
                conflict_id,
                requester_id=mission_id,
                reason=f"Preempted by {runtime.mission.name}",
            )

        with self._condition:
            runtime = self._runtime_locked(mission_id)
            conflicts = self._conflicts_locked(runtime.mission)
            if conflicts:
                return self._queue_locked(runtime, reason or "Waiting for resources")
            runtime.stop_event.clear()
            runtime.cleaned = False
            snapshot = self._transition_locked(
                runtime,
                MissionPhase.STARTING,
                reason=reason,
                requester_id=requester_id,
            )
            generation = snapshot.generation
            worker = threading.Thread(
                target=self._run_mission,
                args=(mission_id, generation),
                name=f"Mission[{runtime.mission.name}:{mission_id}]",
                daemon=True,
            )
            runtime.worker = worker
            worker.start()
            return snapshot

    run = launch

    def launch_many(self, *missions: MissionReference) -> tuple[MissionSnapshot, ...]:
        """Launch independent missions; non-conflicting work runs in parallel."""

        return tuple(self.launch(mission) for mission in missions)

    run_parallel = launch_many

    def start_chain(self, chain: MissionChain) -> MissionChainSnapshot:
        if not isinstance(chain, MissionChain):
            raise TypeError("Mission engine chains must be MissionChain instances")
        with self._condition:
            current = self._chains.get(chain.chain_id)
            if current is not None and current.active:
                raise MissionConflictError(f"Mission chain is already active: {chain.chain_id}")
            snapshot = MissionChainSnapshot(chain=chain, active=True)
            self._chains[chain.chain_id] = snapshot
        self._emit(MissionEventType.CHAIN, f"Mission chain started: {chain.chain_id}")
        self._launch_chain_index(chain.chain_id, 0)
        with self._condition:
            return self._chains[chain.chain_id]

    def chain_snapshot(self, chain_id: str) -> MissionChainSnapshot:
        with self._condition:
            try:
                return self._chains[str(chain_id).strip()]
            except KeyError as exc:
                raise MissionNotFoundError(f"Mission chain not found: {chain_id}") from exc

    def _scheduler_loop(self) -> None:
        while not self._scheduler_stop.is_set():
            self._scheduler_wake.wait(self._scheduler_interval)
            self._scheduler_wake.clear()
            if self._scheduler_stop.is_set():
                break
            self._promote_queued()

    def _promote_queued(self) -> None:
        now = time.time()
        with self._condition:
            queued = sorted(
                (
                    runtime
                    for runtime in self._runtimes.values()
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
                self.fail(runtime.mission.id, "Mission queue timed out")
                continue
            if snapshot.next_retry_at is not None and now < snapshot.next_retry_at:
                continue
            try:
                self.launch(runtime.mission.id, reason="Queued mission released")
            except MissionConflictError:
                continue

    def _after_terminal(self, mission_id: int, *, succeeded: bool) -> None:
        self._scheduler_wake.set()
        with self._condition:
            chain_id = self._mission_chains.pop(mission_id, None)
            if chain_id is not None and not self._running:
                chain = self._chains.get(chain_id)
                if chain is not None and chain.active:
                    self._chains[chain_id] = replace(
                        chain,
                        active=False,
                        failed=True,
                        reason="Mission engine stopped",
                    )
                chain_id = None
        if chain_id is not None:
            self._advance_chain(chain_id, succeeded=succeeded)

    def _launch_chain_index(self, chain_id: str, index: int) -> None:
        with self._condition:
            snapshot = self._chains[chain_id]
            mission_type = snapshot.chain.mission_types[index]
        mission = self._mission_factory(mission_type)
        if not isinstance(mission, mission_type):
            raise MissionRegistrationError(
                "Mission factory must return an instance of the requested type"
            )
        self.register(mission)
        with self._condition:
            self._mission_chains[mission.id] = chain_id
        self.launch(mission)

    def _advance_chain(self, chain_id: str, *, succeeded: bool) -> None:
        with self._condition:
            snapshot = self._chains.get(chain_id)
            if snapshot is None or not snapshot.active:
                return
            if not succeeded and snapshot.chain.stop_on_failure:
                self._chains[chain_id] = replace(
                    snapshot,
                    active=False,
                    failed=True,
                    reason="Mission in chain failed",
                )
                self._emit(MissionEventType.CHAIN, f"Mission chain failed: {chain_id}")
                return
            next_index = snapshot.current_index + 1
            if next_index >= len(snapshot.chain.mission_types):
                self._chains[chain_id] = replace(
                    snapshot,
                    current_index=next_index,
                    active=False,
                    completed=True,
                )
                self._emit(MissionEventType.CHAIN, f"Mission chain completed: {chain_id}")
                return
            self._chains[chain_id] = replace(snapshot, current_index=next_index)
        self._launch_chain_index(chain_id, next_index)

    def _missing_prerequisites_locked(
        self,
        mission: Mission,
    ) -> tuple[type[Mission], ...]:
        succeeded_types = {
            type(runtime.mission)
            for runtime in self._runtimes.values()
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
        for runtime in self._runtimes.values():
            other = runtime.mission
            if other.id == mission.id or not runtime.snapshot.phase.active:
                continue
            resource_conflict = bool(mission.resources & other.resources)
            type_conflict = any(isinstance(other, blocked) for blocked in mission.blocks)
            reverse_conflict = any(isinstance(mission, blocked) for blocked in other.blocks)
            if resource_conflict or type_conflict or reverse_conflict:
                conflicts.append(runtime)
        return tuple(conflicts)
