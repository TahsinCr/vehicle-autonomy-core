"""Owner-bound background mission lifecycle."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .base import Mission
from .enums import (
    BackgroundFailurePolicy,
    MissionEventType,
    MissionPhase,
    OwnerTerminationPolicy,
)
from .errors import MissionConflictError, MissionNotFoundError
from .execution import (
    MissionBackgroundSnapshot,
    MissionChainSnapshot,
    MissionExecutionContext,
    MissionParallelSnapshot,
)

if TYPE_CHECKING:
    from .engine import MissionEngine
    from .orchestration import MissionOrchestrator


MissionOwner = Mission | int | MissionChainSnapshot | MissionParallelSnapshot


class MissionBackgroundExecutor:
    """Own background mission relationships and propagation policies."""

    def __init__(self, orchestrator: "MissionOrchestrator") -> None:
        self.orchestrator = orchestrator
        self._missions: dict[int, MissionBackgroundSnapshot] = {}

    @property
    def engine(self) -> "MissionEngine":
        return self.orchestrator.engine

    def launch(
        self,
        mission: Mission,
        *,
        owner: MissionOwner,
        termination_policy: OwnerTerminationPolicy = (
            OwnerTerminationPolicy.STOP_WITH_OWNER
        ),
        failure_policy: BackgroundFailurePolicy = BackgroundFailurePolicy.IGNORE,
    ) -> MissionBackgroundSnapshot:
        owner_kind, owner_id = self._owner_identity(owner)
        self._ensure_owner_active(owner_kind, owner_id)
        self.engine.register(mission)
        snapshot = MissionBackgroundSnapshot(
            mission.id,
            owner_kind,
            owner_id,
            termination_policy,
            failure_policy,
        )
        with self.engine._condition:
            self._missions[mission.id] = snapshot
            runtime = self.engine._runtime_locked(mission.id)
            runtime.chain_context = self._owner_context(owner_kind, owner_id)
        self.engine._emit(
            MissionEventType.BACKGROUND,
            f"Background mission started: {mission.name}",
            mission_id=mission.id,
            fields={"owner_kind": owner_kind, "owner_id": owner_id},
        )
        with self.engine._condition:
            if not self._missions[mission.id].active:
                return self._missions[mission.id]
        try:
            self.engine.launch(mission)
        except Exception:
            with self.engine._condition:
                runtime = self.engine._runtime_locked(mission.id)
                runtime.chain_context = None
                runtime.execution_node = None
                self._missions[mission.id] = replace(
                    snapshot,
                    active=False,
                    phase=runtime.snapshot.phase,
                )
            raise
        with self.engine._condition:
            abandoned = not self._missions[mission.id].active
            phase = self.engine._runtime_locked(mission.id).snapshot.phase
        if abandoned and not phase.terminal:
            self.engine.stop_mission(
                mission.id,
                reason="Background owner terminated during launch",
            )
        return self.snapshot(mission.id)

    def snapshot(self, mission_id: int) -> MissionBackgroundSnapshot:
        mission_id = int(mission_id)
        with self.engine._condition:
            try:
                snapshot = self._missions[mission_id]
            except KeyError as exc:
                raise MissionNotFoundError(
                    f"Background mission not found: {mission_id}"
                ) from exc
            phase = self.engine._runtime_locked(mission_id).snapshot.phase
            active = snapshot.active and not phase.terminal
            if phase is not snapshot.phase or active != snapshot.active:
                snapshot = replace(snapshot, active=active, phase=phase)
                self._missions[mission_id] = snapshot
            return snapshot

    def contains(self, mission_id: int) -> bool:
        with self.engine._condition:
            return mission_id in self._missions

    def after_terminal(self, mission_id: int, phase: MissionPhase) -> None:
        with self.engine._condition:
            snapshot = self._missions.get(mission_id)
            if snapshot is None:
                return
            runtime = self.engine._runtime_locked(mission_id)
            runtime.chain_context = None
            runtime.execution_node = None
            self._missions[mission_id] = replace(
                snapshot,
                active=False,
                phase=phase,
            )
        if phase is MissionPhase.FAILED:
            self._apply_failure(snapshot)

    def owner_terminated(
        self,
        owner_kind: str,
        owner_id: str,
        phase: MissionPhase,
    ) -> None:
        with self.engine._condition:
            backgrounds = tuple(
                item
                for item in self._missions.values()
                if item.active
                and item.owner_kind == owner_kind
                and item.owner_id == owner_id
            )
        for background in backgrounds:
            if background.termination_policy is OwnerTerminationPolicy.KEEP_RUNNING:
                continue
            if (
                background.termination_policy
                is OwnerTerminationPolicy.CANCEL_WITH_OWNER
                and phase in {MissionPhase.CANCELLED, MissionPhase.FAILED}
            ):
                self.engine.cancel(
                    background.mission_id,
                    reason="Background owner terminated",
                )
            else:
                self.engine.stop_mission(
                    background.mission_id,
                    reason="Background owner terminated",
                )

    def clear(self) -> None:
        with self.engine._condition:
            self._missions.clear()

    def forget_mission(self, mission_id: int) -> None:
        with self.engine._condition:
            self._missions.pop(mission_id, None)

    def _apply_failure(self, background: MissionBackgroundSnapshot) -> None:
        if background.failure_policy is BackgroundFailurePolicy.IGNORE:
            return
        if background.owner_kind == "mission":
            owner_id = int(background.owner_id)
            runtime = self.engine._runtime(owner_id)
            if not runtime.snapshot.phase.active:
                return
            if background.failure_policy is BackgroundFailurePolicy.FAIL_OWNER:
                self.engine.fail(owner_id, "Owned background mission failed")
            else:
                self.engine.stop_mission(
                    owner_id,
                    reason="Owned background mission failed",
                )
        elif background.owner_kind == "chain":
            if background.failure_policy is BackgroundFailurePolicy.FAIL_OWNER:
                self.orchestrator.chains.fail(
                    background.owner_id,
                    "Owned background mission failed",
                )
            else:
                self.orchestrator.chains.stop(background.owner_id)
        elif background.owner_kind == "parallel":
            if background.failure_policy is BackgroundFailurePolicy.FAIL_OWNER:
                self.orchestrator.parallel.fail(
                    background.owner_id,
                    "Owned background mission failed",
                )
            else:
                self.orchestrator.parallel.stop(background.owner_id)

    @staticmethod
    def _owner_identity(owner: MissionOwner) -> tuple[str, str]:
        if isinstance(owner, MissionChainSnapshot):
            return "chain", owner.execution_id
        if isinstance(owner, MissionParallelSnapshot):
            return "parallel", owner.execution_id
        if isinstance(owner, Mission):
            return "mission", str(owner.id)
        return "mission", str(int(owner))

    def _ensure_owner_active(self, owner_kind: str, owner_id: str) -> None:
        if owner_kind == "mission":
            active = self.engine._runtime(int(owner_id)).snapshot.phase.active
        elif owner_kind == "chain":
            active = self.orchestrator.chains.is_active(owner_id)
        else:
            active = self.orchestrator.parallel.is_active(owner_id)
        if not active:
            raise MissionConflictError("Background mission owner must be active")

    def _owner_context(
        self,
        owner_kind: str,
        owner_id: str,
    ) -> MissionExecutionContext | None:
        if owner_kind == "mission":
            return self.engine._runtime_locked(int(owner_id)).chain_context
        if owner_kind == "chain":
            return self.orchestrator.chains.context(owner_id)
        chain_id = self.orchestrator.parallel.chain_execution(owner_id)
        return (
            None
            if chain_id is None
            else self.orchestrator.chains.context(chain_id)
        )
