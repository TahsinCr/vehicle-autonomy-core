"""Coordination boundary for mission execution components."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from ..compatibility import ExceptionGroup

from .background import MissionBackgroundExecutor
from .chain import MissionChainExecutor
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

    @staticmethod
    def mission_for(node: MissionNode) -> "Mission":
        """Return the configured mission owned by one execution node."""

        return node.mission

    def is_pending(self, mission_id: int) -> bool:
        """Return whether a child can still participate in an execution."""

        from .enums import MissionPhase

        with self.engine._condition:
            phase = self.engine._runtime_locked(mission_id).snapshot.phase
        return phase.active or phase in {
            MissionPhase.REGISTERED,
            MissionPhase.QUEUED,
        }

    @staticmethod
    def retain_bounded_execution(
        completed: deque[str],
        execution_id: str,
        limit: int,
        remove: Callable[[str], None],
    ) -> None:
        """Retain one terminal execution while enforcing its history bound."""

        if execution_id not in completed:
            completed.append(execution_id)
        while len(completed) > limit:
            remove(completed.popleft())

    def forget_mission(self, mission_id: int) -> None:
        self.chains.forget_mission(mission_id)
        self.parallel.forget_mission(mission_id)
        self.background.forget_mission(mission_id)

    def clear(self) -> None:
        self.chains.clear()
        self.parallel.clear()
        self.background.clear()

    @staticmethod
    def run_all(operations: Iterable[Callable[[], object]], message: str) -> None:
        """Attempt every lifecycle command and report all failures together."""

        errors: list[Exception] = []
        for operation in operations:
            try:
                operation()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup(message, errors)
