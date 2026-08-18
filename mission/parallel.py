"""Controlled parallel mission group execution."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

from .base import Mission
from .enums import MissionEventType, MissionPhase, ParallelFailurePolicy
from .errors import MissionConflictError, MissionNotFoundError, MissionRegistrationError
from .execution import (
    MissionExecutionContext,
    MissionExecutionResult,
    MissionNode,
    MissionParallelGroup,
    MissionParallelSnapshot,
)

if TYPE_CHECKING:
    from .engine import MissionEngine
    from .orchestration import MissionOrchestrator


class MissionParallelExecutor:
    """Own named parallel runs, children, results, and failure policies."""

    def __init__(self, orchestrator: "MissionOrchestrator") -> None:
        self.orchestrator = orchestrator
        self._runs: dict[str, MissionParallelSnapshot] = {}
        self._latest: dict[str, str] = {}
        self._mission_runs: dict[int, str] = {}
        self._chain_runs: dict[str, str] = {}

    @property
    def engine(self) -> "MissionEngine":
        return self.orchestrator.engine

    def start(
        self,
        group: MissionParallelGroup,
        *,
        chain_execution_id: str | None = None,
        chain_context: MissionExecutionContext | None = None,
    ) -> MissionParallelSnapshot:
        if not isinstance(group, MissionParallelGroup):
            raise TypeError("Parallel execution requires MissionParallelGroup")
        execution_id = uuid4().hex
        missions = tuple(
            (node, self.orchestrator.create_mission(node))
            for node in group.nodes
        )
        if len({mission.id for _node, mission in missions}) != len(missions):
            raise MissionRegistrationError(
                "Mission factory returned the same instance for multiple nodes"
            )
        self._validate_conflicts(missions)
        registered: list[Mission] = []
        try:
            for _node, mission in missions:
                self.engine.register(mission)
                registered.append(mission)
        except Exception:
            for mission in reversed(registered):
                self.engine.unregister(mission)
            raise

        children = {node.name: mission.id for node, mission in missions}
        snapshot = MissionParallelSnapshot(
            group,
            execution_id,
            children=children,
            phases={name: MissionPhase.REGISTERED for name in children},
        )
        with self.engine._condition:
            self._runs[execution_id] = snapshot
            self._latest[group.group_id] = execution_id
            if chain_execution_id is not None:
                self._chain_runs[execution_id] = chain_execution_id
            for _node, mission in missions:
                self._mission_runs[mission.id] = execution_id
                self.engine._runtime_locked(mission.id).chain_context = chain_context
        self.engine._emit(
            MissionEventType.PARALLEL,
            f"Parallel execution started: {group.group_id}",
            fields={"group_id": group.group_id, "execution_id": execution_id},
        )
        try:
            for _node, mission in missions:
                with self.engine._condition:
                    if not self._runs[execution_id].active:
                        break
                self.engine.launch(mission)
        except Exception as exc:
            self.fail(execution_id, f"Parallel launch failed: {exc}")
            raise
        return self.snapshot(execution_id)

    def snapshot(self, identifier: str) -> MissionParallelSnapshot:
        with self.engine._condition:
            execution_id = self._latest.get(identifier, identifier)
            try:
                return self._runs[execution_id]
            except KeyError as exc:
                raise MissionNotFoundError(
                    f"Parallel execution not found: {identifier}"
                ) from exc

    def stop(self, identifier: str) -> MissionParallelSnapshot:
        return self._terminate(identifier, cancelled=False)

    def cancel(self, identifier: str) -> MissionParallelSnapshot:
        return self._terminate(identifier, cancelled=True)

    def execution_for_mission(self, mission_id: int) -> str | None:
        with self.engine._condition:
            return self._mission_runs.get(mission_id)

    def after_terminal(self, execution_id: str, mission_id: int) -> None:
        try:
            self._advance(execution_id, mission_id)
        except ValueError as exc:
            self.fail(execution_id, str(exc))

    def fail(self, execution_id: str, reason: str) -> None:
        with self.engine._condition:
            snapshot = self._runs.get(execution_id)
            if snapshot is None:
                return
            self._runs[execution_id] = replace(
                snapshot,
                active=False,
                failed=True,
                reason=reason,
            )
            children = tuple(snapshot.children.values())
            chain_id = self._chain_runs.pop(execution_id, None)
        for mission_id in children:
            runtime = self.engine._runtime(mission_id)
            phase = runtime.snapshot.phase
            if (
                phase.active
                or phase is MissionPhase.QUEUED
                or phase is MissionPhase.REGISTERED
            ):
                self.engine.stop_mission(mission_id, reason=reason)
        self.orchestrator.background.owner_terminated(
            "parallel",
            execution_id,
            MissionPhase.FAILED,
        )
        if chain_id is not None:
            self.orchestrator.chains.fail(chain_id, reason)

    def is_active(self, execution_id: str) -> bool:
        with self.engine._condition:
            snapshot = self._runs.get(execution_id)
            return bool(snapshot and snapshot.active)

    def chain_execution(self, execution_id: str) -> str | None:
        with self.engine._condition:
            return self._chain_runs.get(execution_id)

    def active_children_for_chain_locked(self, chain_id: str) -> tuple[int, ...]:
        return tuple(
            mission_id
            for group_id, owner_chain_id in self._chain_runs.items()
            if owner_chain_id == chain_id
            for mission_id in self._runs[group_id].children.values()
            if self._is_pending(mission_id)
        )

    def forget_mission(self, mission_id: int) -> None:
        with self.engine._condition:
            self._mission_runs.pop(mission_id, None)

    def clear(self) -> None:
        with self.engine._condition:
            self._runs.clear()
            self._latest.clear()
            self._mission_runs.clear()
            self._chain_runs.clear()

    def _advance(self, execution_id: str, mission_id: int) -> None:
        actions: tuple[str, tuple[int, ...]] | None = None
        chain_id: str | None = None
        terminal: MissionExecutionResult | None = None
        owner_phase: MissionPhase | None = None
        with self.engine._condition:
            snapshot = self._runs.get(execution_id)
            if snapshot is None:
                return
            node = next(
                name
                for name, child_id in snapshot.children.items()
                if child_id == mission_id
            )
            runtime = self.engine._runtime_locked(mission_id)
            phase = runtime.snapshot.phase
            phases = dict(snapshot.phases)
            results = dict(snapshot.results)
            phases[node] = phase
            results[node] = runtime.snapshot.result
            runtime.chain_context = None
            runtime.execution_node = None
            remaining = tuple(
                child_id
                for child_name, child_id in snapshot.children.items()
                if child_name != node
                and self.engine._runtime_locked(child_id).snapshot.phase.active
            )
            reason = snapshot.reason
            if phase is MissionPhase.FAILED and remaining and not reason:
                if (
                    snapshot.group.failure_policy
                    is ParallelFailurePolicy.CANCEL_REMAINING
                ):
                    actions = ("cancel", remaining)
                    reason = f"Child {node} failed; cancelling siblings"
                elif (
                    snapshot.group.failure_policy
                    is ParallelFailurePolicy.STOP_REMAINING
                ):
                    actions = ("stop", remaining)
                    reason = f"Child {node} failed; stopping siblings"
            all_terminal = all(item.terminal for item in phases.values())
            updated = replace(snapshot, phases=phases, results=results, reason=reason)
            if all_terminal:
                values = tuple(phases.values())
                succeeded = all(item is MissionPhase.SUCCEEDED for item in values)
                updated = replace(
                    updated,
                    active=False,
                    completed=succeeded,
                    failed=(
                        snapshot.failed
                        or any(item is MissionPhase.FAILED for item in values)
                    ),
                    cancelled=any(item is MissionPhase.CANCELLED for item in values),
                    stopped=any(item is MissionPhase.STOPPED for item in values),
                )
                if succeeded:
                    owner_phase = MissionPhase.SUCCEEDED
                elif any(item is MissionPhase.FAILED for item in values):
                    owner_phase = MissionPhase.FAILED
                elif any(item is MissionPhase.CANCELLED for item in values):
                    owner_phase = MissionPhase.CANCELLED
                else:
                    owner_phase = MissionPhase.STOPPED
                chain_id = self._chain_runs.pop(execution_id, None)
                terminal = MissionExecutionResult(
                    snapshot.group.group_id,
                    mission_id,
                    owner_phase,
                    results,
                )
            self._runs[execution_id] = updated
            self._mission_runs.pop(mission_id, None)
        if actions is not None:
            operation, mission_ids = actions
            self.engine._emit(
                MissionEventType.PARALLEL,
                f"Parallel sibling {operation} requested: {execution_id}",
                fields={"execution_id": execution_id, "child_count": len(mission_ids)},
            )
            for child_id in mission_ids:
                if operation == "cancel":
                    self.engine.cancel(child_id, reason="Parallel sibling failed")
                else:
                    self.engine.stop_mission(
                        child_id,
                        reason="Parallel sibling failed",
                    )
        if owner_phase is not None:
            self.engine._emit(
                MissionEventType.PARALLEL,
                f"Parallel execution finished: {execution_id}",
                fields={"execution_id": execution_id, "phase": owner_phase.value},
            )
            self.orchestrator.background.owner_terminated(
                "parallel",
                execution_id,
                owner_phase,
            )
            if chain_id is not None and terminal is not None:
                self.orchestrator.chains.advance(chain_id, terminal)

    def _terminate(
        self,
        identifier: str,
        *,
        cancelled: bool,
    ) -> MissionParallelSnapshot:
        snapshot = self.snapshot(identifier)
        with self.engine._condition:
            if not snapshot.active:
                return snapshot
            terminal = (
                MissionPhase.CANCELLED if cancelled else MissionPhase.STOPPED
            )
            reason = (
                "Parallel execution cancelled"
                if cancelled
                else "Parallel execution stopped"
            )
            children = tuple(
                mission_id
                for mission_id in snapshot.children.values()
                if self._is_pending(mission_id)
            )
            self._runs[snapshot.execution_id] = replace(
                snapshot,
                active=False,
                cancelled=cancelled,
                stopped=not cancelled,
                reason=reason,
            )
            self._chain_runs.pop(snapshot.execution_id, None)
        for mission_id in children:
            if cancelled:
                self.engine.cancel(mission_id, reason=reason)
            else:
                self.engine.stop_mission(mission_id, reason=reason)
        self.orchestrator.background.owner_terminated(
            "parallel",
            snapshot.execution_id,
            terminal,
        )
        return self.snapshot(snapshot.execution_id)

    def _is_pending(self, mission_id: int) -> bool:
        phase = self.engine._runtime_locked(mission_id).snapshot.phase
        return phase.active or phase in {
            MissionPhase.REGISTERED,
            MissionPhase.QUEUED,
        }

    @staticmethod
    def _validate_conflicts(
        missions: tuple[tuple[MissionNode, Mission], ...],
    ) -> None:
        for index, (node, mission) in enumerate(missions):
            for other_node, other in missions[index + 1:]:
                if (
                    mission.resources & other.resources
                    or any(isinstance(other, blocked) for blocked in mission.blocks)
                    or any(isinstance(mission, blocked) for blocked in other.blocks)
                ):
                    raise MissionConflictError(
                        f"Parallel nodes conflict: {node.name}, {other_node.name}"
                    )
