"""Sequential and mixed-stage mission chain execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .enums import MissionEventType, MissionPhase
from .errors import MissionNotFoundError
from .execution import (
    MissionChain,
    MissionChainSnapshot,
    MissionExecutionContext,
    MissionExecutionResult,
    MissionNode,
    MissionParallelGroup,
    MissionParallelStage,
)

if TYPE_CHECKING:
    from .engine import MissionEngine
    from .orchestration import MissionOrchestrator


class MissionChainExecutor:
    """Own chain definitions, execution context, and stage advancement."""

    def __init__(self, orchestrator: "MissionOrchestrator") -> None:
        self.orchestrator = orchestrator
        self._runs: dict[str, MissionChainSnapshot] = {}
        self._latest: dict[str, str] = {}
        self._mission_runs: dict[int, str] = {}

    @property
    def engine(self) -> "MissionEngine":
        return self.orchestrator.engine

    def start(
        self,
        chain: MissionChain,
        *,
        input: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MissionChainSnapshot:
        if not isinstance(chain, MissionChain):
            raise TypeError("Mission chains must be MissionChain instances")
        execution_id = uuid4().hex
        context = MissionExecutionContext(
            chain.chain_id,
            execution_id,
            0,
            input or {},
            metadata or {},
        )
        snapshot = MissionChainSnapshot(
            chain,
            execution_id=execution_id,
            active=True,
            context=context,
        )
        with self.engine._condition:
            self._runs[execution_id] = snapshot
            self._latest[chain.chain_id] = execution_id
        self.engine._emit(
            MissionEventType.CHAIN,
            f"Mission chain started: {chain.chain_id}",
            fields={"chain_id": chain.chain_id, "execution_id": execution_id},
        )
        try:
            self._launch_stage(execution_id)
        except Exception as exc:
            self.fail(execution_id, f"Mission chain could not start: {exc}")
            raise
        return self.snapshot(execution_id)

    def snapshot(self, identifier: str) -> MissionChainSnapshot:
        with self.engine._condition:
            execution_id = self._latest.get(identifier, identifier)
            try:
                return self._runs[execution_id]
            except KeyError as exc:
                raise MissionNotFoundError(
                    f"Mission chain execution not found: {identifier}"
                ) from exc

    def stop(self, identifier: str) -> MissionChainSnapshot:
        return self._terminate(identifier, cancelled=False)

    def cancel(self, identifier: str) -> MissionChainSnapshot:
        return self._terminate(identifier, cancelled=True)

    def execution_for_mission(self, mission_id: int) -> str | None:
        with self.engine._condition:
            return self._mission_runs.pop(mission_id, None)

    def after_terminal(self, execution_id: str, mission_id: int) -> None:
        if not self.engine.running:
            with self.engine._condition:
                runtime = self.engine._runtime_locked(mission_id)
                runtime.chain_context = None
                runtime.execution_node = None
            self.fail(execution_id, "Mission engine stopped")
            return
        try:
            self._advance_mission(execution_id, mission_id)
        except ValueError as exc:
            self.fail(execution_id, str(exc))

    def advance(
        self,
        execution_id: str,
        terminal: MissionExecutionResult,
    ) -> None:
        launch_next = False
        owner_phase: MissionPhase | None = None
        with self.engine._condition:
            snapshot = self._runs.get(execution_id)
            if snapshot is None or not snapshot.active or snapshot.context is None:
                return
            results = dict(snapshot.context.results)
            results[terminal.node] = terminal.result
            unsuccessful = terminal.phase is not MissionPhase.SUCCEEDED
            interrupted = terminal.phase in {
                MissionPhase.CANCELLED,
                MissionPhase.STOPPED,
            }
            if interrupted or (unsuccessful and snapshot.chain.stop_on_failure):
                context = replace(
                    snapshot.context,
                    previous_mission=terminal,
                    previous_result=terminal.result,
                    results=results,
                )
                self._runs[execution_id] = replace(
                    snapshot,
                    active=False,
                    failed=terminal.phase is MissionPhase.FAILED,
                    cancelled=terminal.phase is MissionPhase.CANCELLED,
                    stopped=terminal.phase is MissionPhase.STOPPED,
                    reason=f"Mission stage ended as {terminal.phase.value}",
                    context=context,
                )
                owner_phase = terminal.phase
            else:
                next_index = snapshot.current_index + 1
                context = MissionExecutionContext(
                    snapshot.chain.chain_id,
                    execution_id,
                    next_index,
                    snapshot.context.input,
                    snapshot.context.metadata,
                    terminal,
                    terminal.result,
                    results,
                )
                accumulated_failure = unsuccessful or snapshot.failed
                if next_index >= len(snapshot.chain.stages):
                    self._runs[execution_id] = replace(
                        snapshot,
                        current_index=next_index,
                        active=False,
                        completed=True,
                        failed=accumulated_failure,
                        context=context,
                    )
                    owner_phase = (
                        MissionPhase.FAILED
                        if accumulated_failure
                        else MissionPhase.SUCCEEDED
                    )
                else:
                    self._runs[execution_id] = replace(
                        snapshot,
                        current_index=next_index,
                        failed=accumulated_failure,
                        context=context,
                    )
                    launch_next = True
        if owner_phase is not None:
            self.engine._emit(
                MissionEventType.CHAIN,
                f"Mission chain finished: {execution_id}",
                fields={"execution_id": execution_id, "phase": owner_phase.value},
            )
            self.orchestrator.background.owner_terminated(
                "chain",
                execution_id,
                owner_phase,
            )
        elif launch_next:
            self.engine._emit(
                MissionEventType.CHAIN,
                f"Mission chain advanced: {execution_id}",
                fields={
                    "execution_id": execution_id,
                    "result_keys": tuple(terminal.result),
                },
            )
            try:
                self._launch_stage(execution_id)
            except Exception as exc:
                self.fail(
                    execution_id,
                    f"Mission chain could not continue: {exc}",
                )

    def fail(self, execution_id: str, reason: str) -> None:
        with self.engine._condition:
            snapshot = self._runs.get(execution_id)
            if snapshot is None or not snapshot.active:
                return
            self._runs[execution_id] = replace(
                snapshot,
                active=False,
                failed=True,
                reason=reason,
            )
            children = self._active_children_locked(execution_id)
        for mission_id in children:
            self.engine.stop_mission(mission_id, reason=reason)
        self.engine._emit(
            MissionEventType.CHAIN,
            reason,
            fields={"execution_id": execution_id},
        )
        self.orchestrator.background.owner_terminated(
            "chain",
            execution_id,
            MissionPhase.FAILED,
        )

    def context(self, execution_id: str) -> MissionExecutionContext | None:
        with self.engine._condition:
            snapshot = self._runs.get(execution_id)
            return None if snapshot is None else snapshot.context

    def is_active(self, execution_id: str) -> bool:
        with self.engine._condition:
            snapshot = self._runs.get(execution_id)
            return bool(snapshot and snapshot.active)

    def forget_mission(self, mission_id: int) -> None:
        with self.engine._condition:
            self._mission_runs.pop(mission_id, None)

    def clear(self) -> None:
        with self.engine._condition:
            self._runs.clear()
            self._latest.clear()
            self._mission_runs.clear()

    def _launch_stage(self, execution_id: str) -> None:
        with self.engine._condition:
            snapshot = self._runs[execution_id]
            if not snapshot.active:
                return
            entry = snapshot.chain.stages[snapshot.current_index]
            context = snapshot.context
        if isinstance(entry, MissionParallelStage):
            group = MissionParallelGroup(entry.name, entry.nodes, entry.failure_policy)
            parallel = self.orchestrator.parallel.start(
                group,
                chain_execution_id=execution_id,
                chain_context=context,
            )
            with self.engine._condition:
                current = self._runs[execution_id]
                self._runs[execution_id] = replace(
                    current,
                    child_mission_ids=(
                        current.child_mission_ids
                        + tuple(parallel.children.values())
                    ),
                )
            return

        node = entry if isinstance(entry, MissionNode) else MissionNode(
            self._node_name(snapshot),
            entry,
        )
        mission = self.orchestrator.create_mission(node)
        self.engine.register(mission)
        with self.engine._condition:
            runtime = self.engine._runtime_locked(mission.id)
            runtime.chain_context = context
            runtime.execution_node = node.name
            self._mission_runs[mission.id] = execution_id
            current = self._runs[execution_id]
            self._runs[execution_id] = replace(
                current,
                child_mission_ids=current.child_mission_ids + (mission.id,),
            )
        try:
            self.engine.launch(mission)
        except Exception:
            with self.engine._condition:
                runtime = self.engine._runtime_locked(mission.id)
                runtime.chain_context = None
                runtime.execution_node = None
                self._mission_runs.pop(mission.id, None)
            self.engine.unregister(mission)
            raise

    def _advance_mission(self, execution_id: str, mission_id: int) -> None:
        with self.engine._condition:
            runtime = self.engine._runtime_locked(mission_id)
            context = runtime.chain_context
            runtime.chain_context = None
            node = runtime.execution_node or type(runtime.mission).__name__
            runtime.execution_node = None
            if context is None:
                return
            terminal = MissionExecutionResult(
                node,
                mission_id,
                runtime.snapshot.phase,
                runtime.snapshot.result,
            )
        self.advance(execution_id, terminal)

    def _terminate(
        self,
        identifier: str,
        *,
        cancelled: bool,
    ) -> MissionChainSnapshot:
        snapshot = self.snapshot(identifier)
        with self.engine._condition:
            if not snapshot.active:
                return snapshot
            reason = (
                "Mission chain cancelled" if cancelled else "Mission chain stopped"
            )
            self._runs[snapshot.execution_id] = replace(
                snapshot,
                active=False,
                cancelled=cancelled,
                stopped=not cancelled,
                reason=reason,
            )
            children = self._active_children_locked(snapshot.execution_id)
        for mission_id in children:
            if cancelled:
                self.engine.cancel(mission_id, reason=reason)
            else:
                self.engine.stop_mission(mission_id, reason=reason)
        phase = MissionPhase.CANCELLED if cancelled else MissionPhase.STOPPED
        self.orchestrator.background.owner_terminated(
            "chain",
            snapshot.execution_id,
            phase,
        )
        return self.snapshot(snapshot.execution_id)

    def _active_children_locked(self, execution_id: str) -> tuple[int, ...]:
        direct = tuple(
            mission_id
            for mission_id, chain_id in self._mission_runs.items()
            if chain_id == execution_id
            and self._is_pending(mission_id)
        )
        return direct + self.orchestrator.parallel.active_children_for_chain_locked(
            execution_id
        )

    def _is_pending(self, mission_id: int) -> bool:
        phase = self.engine._runtime_locked(mission_id).snapshot.phase
        return phase.active or phase in {
            MissionPhase.REGISTERED,
            MissionPhase.QUEUED,
        }

    @staticmethod
    def _node_name(snapshot: MissionChainSnapshot) -> str:
        entry = snapshot.chain.stages[snapshot.current_index]
        if not isinstance(entry, type):
            raise TypeError("Sequential chain entries must be mission types or nodes")
        occurrence = sum(
            1
            for previous in snapshot.chain.stages[:snapshot.current_index]
            if previous is entry
        )
        return (
            entry.__name__
            if occurrence == 0
            else f"{entry.__name__}#{occurrence + 1}"
        )
