"""Coordination boundary for mission execution components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .background import MissionBackgroundExecutor
from .chain import MissionChainExecutor
from .errors import MissionRegistrationError
from .execution import MissionNode
from .parallel import MissionParallelExecutor

if TYPE_CHECKING:
    from .base import Mission
    from .engine import MissionEngine


class MissionOrchestrator:
    """Connect chain, parallel, and background execution components."""

    def __init__(self, engine: "MissionEngine") -> None:
        self.engine = engine
        self.chains = MissionChainExecutor(self)
        self.parallel = MissionParallelExecutor(self)
        self.background = MissionBackgroundExecutor(self)

    def after_terminal(self, mission_id: int) -> None:
        """Route one terminal mission to each owning execution."""

        self.engine._scheduler_wake.set()
        with self.engine._condition:
            phase = self.engine._runtime_locked(mission_id).snapshot.phase
        chain_id = self.chains.execution_for_mission(mission_id)
        group_id = self.parallel.execution_for_mission(mission_id)
        if chain_id is not None:
            self.chains.after_terminal(chain_id, mission_id)
        if group_id is not None:
            self.parallel.after_terminal(group_id, mission_id)
        if self.background.contains(mission_id):
            self.background.after_terminal(mission_id, phase)
        self.background.owner_terminated("mission", str(mission_id), phase)

    def create_mission(self, node: MissionNode) -> "Mission":
        """Create and validate a mission through the engine factory."""

        mission = self.engine._mission_factory(node.mission_type)
        if not isinstance(mission, node.mission_type):
            raise MissionRegistrationError(
                "Mission factory must return the requested mission type"
            )
        return mission

    def forget_mission(self, mission_id: int) -> None:
        self.chains.forget_mission(mission_id)
        self.parallel.forget_mission(mission_id)
        self.background.forget_mission(mission_id)

    def clear(self) -> None:
        self.chains.clear()
        self.parallel.clear()
        self.background.clear()
