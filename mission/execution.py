"""Immutable models used by mission orchestration executions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..abstracts import Model, _copy_model_value, _freeze_model_value
from .enums import (
    BackgroundFailurePolicy,
    MissionPhase,
    OwnerTerminationPolicy,
    ParallelFailurePolicy,
)

if TYPE_CHECKING:
    from .base import Mission


def _json_mapping(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    frozen = _freeze_model_value(value)
    try:
        json.dumps(_copy_model_value(value, lists=True), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON compatible: {exc}") from exc
    return frozen


@dataclass(frozen=True, slots=True)
class MissionExecutionResult(Model):
    """Immutable terminal information passed between execution stages."""

    node: str
    mission_id: int
    phase: MissionPhase
    result: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        node = str(self.node).strip()
        if not node:
            raise ValueError("Mission execution node cannot be empty")
        if self.mission_id <= 0:
            raise ValueError("Mission execution result ID must be positive")
        phase = MissionPhase(self.phase)
        if not phase.terminal:
            raise ValueError("Mission execution result phase must be terminal")
        object.__setattr__(self, "node", node)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(
            self,
            "result",
            _json_mapping(self.result, "Mission result"),
        )


@dataclass(frozen=True, slots=True)
class MissionExecutionContext(Model):
    """Read-only data made available to one chain stage."""

    chain_id: str
    execution_id: str
    current_index: int
    input: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    previous_mission: MissionExecutionResult | None = None
    previous_result: Mapping[str, Any] = field(default_factory=dict)
    results: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        chain_id = str(self.chain_id).strip()
        execution_id = str(self.execution_id).strip()
        if not chain_id or not execution_id:
            raise ValueError("Chain and execution IDs cannot be empty")
        if self.current_index < 0:
            raise ValueError("Mission execution index cannot be negative")
        if self.previous_mission is not None and not isinstance(
            self.previous_mission,
            MissionExecutionResult,
        ):
            raise ValueError("Previous mission must be a MissionExecutionResult")
        object.__setattr__(self, "chain_id", chain_id)
        object.__setattr__(self, "execution_id", execution_id)
        object.__setattr__(self, "input", _json_mapping(self.input, "Chain input"))
        object.__setattr__(
            self,
            "metadata",
            _json_mapping(self.metadata, "Chain metadata"),
        )
        object.__setattr__(
            self,
            "previous_result",
            _json_mapping(self.previous_result, "Previous result"),
        )
        object.__setattr__(
            self,
            "results",
            _json_mapping(self.results, "Chain results"),
        )


@dataclass(frozen=True, slots=True)
class MissionNode(Model):
    """A uniquely named mission inside an execution graph."""

    name: str
    mission_type: type["Mission"]

    def __post_init__(self) -> None:
        from .base import Mission

        name = str(self.name).strip()
        if not name:
            raise ValueError("Mission node name cannot be empty")
        if not isinstance(self.mission_type, type) or not issubclass(
            self.mission_type,
            Mission,
        ):
            raise ValueError("Mission node type must be a Mission subclass")
        object.__setattr__(self, "name", name)


def _mission_nodes(
    values: tuple[MissionNode | type["Mission"], ...],
) -> tuple[MissionNode, ...]:
    nodes: list[MissionNode] = []
    for value in values:
        if isinstance(value, MissionNode):
            nodes.append(value)
        elif isinstance(value, type):
            nodes.append(MissionNode(value.__name__, value))
        else:
            raise ValueError("Parallel entries must be missions or named nodes")
    return tuple(nodes)


@dataclass(frozen=True, slots=True)
class MissionParallelStage(Model):
    """A named set of missions launched as one chain stage."""

    name: str
    nodes: tuple[MissionNode | type["Mission"], ...]
    failure_policy: ParallelFailurePolicy = ParallelFailurePolicy.WAIT_ALL

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        nodes = _mission_nodes(tuple(self.nodes))
        if not name or not nodes:
            raise ValueError("Parallel stage needs a name and at least one node")
        names = tuple(node.name for node in nodes)
        if len(names) != len(set(names)):
            raise ValueError("Parallel stage node names must be unique")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(
            self,
            "failure_policy",
            ParallelFailurePolicy(self.failure_policy),
        )


@dataclass(frozen=True, slots=True)
class MissionParallelGroup(Model):
    """Reusable definition for a controlled parallel mission execution."""

    group_id: str
    nodes: tuple[MissionNode | type["Mission"], ...]
    failure_policy: ParallelFailurePolicy = ParallelFailurePolicy.WAIT_ALL

    def __post_init__(self) -> None:
        stage = MissionParallelStage(self.group_id, self.nodes, self.failure_policy)
        object.__setattr__(self, "group_id", stage.name)
        object.__setattr__(self, "nodes", stage.nodes)
        object.__setattr__(self, "failure_policy", stage.failure_policy)


@dataclass(frozen=True, slots=True)
class MissionChain(Model):
    chain_id: str
    stages: tuple[type["Mission"] | MissionNode | MissionParallelStage, ...]
    stop_on_failure: bool = True

    def __post_init__(self) -> None:
        from .base import Mission

        chain_id = str(self.chain_id).strip()
        if not chain_id:
            raise ValueError("Mission chain ID cannot be empty")
        if not self.stages:
            raise ValueError("Mission chain must contain at least one mission")
        if any(
            not isinstance(entry, (MissionNode, MissionParallelStage))
            and (not isinstance(entry, type) or not issubclass(entry, Mission))
            for entry in self.stages
        ):
            raise ValueError(
                "Mission chain entries must be missions, nodes, or parallel stages"
            )
        node_names: list[str] = []
        type_counts: dict[type[Mission], int] = {}
        for entry in self.stages:
            if isinstance(entry, MissionParallelStage):
                node_names.append(entry.name)
            elif isinstance(entry, MissionNode):
                node_names.append(entry.name)
            else:
                type_counts[entry] = type_counts.get(entry, 0) + 1
                occurrence = type_counts[entry]
                node_names.append(
                    entry.__name__
                    if occurrence == 1
                    else f"{entry.__name__}#{occurrence}"
                )
        if len(node_names) != len(set(node_names)):
            raise ValueError("Mission chain node and stage names must be unique")
        object.__setattr__(self, "chain_id", chain_id)


@dataclass(frozen=True, slots=True)
class MissionChainSnapshot(Model):
    chain: MissionChain
    current_index: int = 0
    active: bool = False
    completed: bool = False
    failed: bool = False
    reason: str = ""
    execution_id: str = ""
    cancelled: bool = False
    stopped: bool = False
    context: MissionExecutionContext | None = None
    child_mission_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.current_index < 0:
            raise ValueError("Mission chain index cannot be negative")
        if self.execution_id and not self.execution_id.strip():
            raise ValueError("Chain execution ID cannot be blank")

    @property
    def current_stage(
        self,
    ) -> type["Mission"] | MissionNode | MissionParallelStage | None:
        if not self.active or self.current_index >= len(self.chain.stages):
            return None
        return self.chain.stages[self.current_index]


@dataclass(frozen=True, slots=True)
class MissionParallelSnapshot(Model):
    group: MissionParallelGroup
    execution_id: str
    active: bool = True
    completed: bool = False
    failed: bool = False
    cancelled: bool = False
    stopped: bool = False
    children: Mapping[str, int] = field(default_factory=dict)
    phases: Mapping[str, MissionPhase] = field(default_factory=dict)
    results: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    reason: str = ""

    def __post_init__(self) -> None:
        if not str(self.execution_id).strip():
            raise ValueError("Parallel execution ID cannot be empty")
        object.__setattr__(self, "children", _freeze_model_value(self.children))
        object.__setattr__(self, "phases", _freeze_model_value(self.phases))
        object.__setattr__(
            self,
            "results",
            _json_mapping(self.results, "Parallel results"),
        )

    @property
    def running(self) -> bool:
        return self.active

    @property
    def result(self) -> Mapping[str, Mapping[str, Any]]:
        """Return the immutable combined result under each node name."""

        return self.results


@dataclass(frozen=True, slots=True)
class MissionBackgroundSnapshot(Model):
    mission_id: int
    owner_kind: str
    owner_id: str
    termination_policy: OwnerTerminationPolicy = (
        OwnerTerminationPolicy.STOP_WITH_OWNER
    )
    failure_policy: BackgroundFailurePolicy = BackgroundFailurePolicy.IGNORE
    active: bool = True
    phase: MissionPhase = MissionPhase.REGISTERED

    def __post_init__(self) -> None:
        if self.mission_id <= 0:
            raise ValueError("Background mission ID must be positive")
        if not str(self.owner_kind).strip() or not str(self.owner_id).strip():
            raise ValueError("Background mission owner cannot be empty")
        object.__setattr__(
            self,
            "termination_policy",
            OwnerTerminationPolicy(self.termination_policy),
        )
        object.__setattr__(
            self,
            "failure_policy",
            BackgroundFailurePolicy(self.failure_policy),
        )
        object.__setattr__(self, "phase", MissionPhase(self.phase))


__all__ = [
    "MissionBackgroundSnapshot",
    "MissionChain",
    "MissionChainSnapshot",
    "MissionExecutionContext",
    "MissionExecutionResult",
    "MissionNode",
    "MissionParallelGroup",
    "MissionParallelSnapshot",
    "MissionParallelStage",
]
