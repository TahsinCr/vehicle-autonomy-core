"""Base class for application-defined missions."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar
from uuid import uuid4

from ..abstracts import Service
from .controller import MissionController
from .enums import (
    MissionConflictPolicy,
    MissionPrerequisitePolicy,
    MissionPriority,
)
from .errors import MissionError, MissionRegistrationError
from .models import MissionRetryPolicy, MissionSnapshot


def _default_mission_name(class_name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", class_name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).strip()


class Mission(Service, ABC):
    """Behavior and configuration shared by all mission implementations."""

    priority: ClassVar[int] = int(MissionPriority.NORMAL)
    resources: ClassVar[frozenset[str]] = frozenset()
    blocks: ClassVar[frozenset[type["Mission"]]] = frozenset()
    tags: ClassVar[frozenset[str]] = frozenset()
    prerequisites: ClassVar[frozenset[type["Mission"]]] = frozenset()
    conflict_policy: ClassVar[MissionConflictPolicy] = MissionConflictPolicy.REJECT
    prerequisite_policy: ClassVar[MissionPrerequisitePolicy] = (
        MissionPrerequisitePolicy.REJECT
    )
    tick_interval: ClassVar[float] = 0.1
    timeout_seconds: ClassVar[float | None] = None
    queue_timeout_seconds: ClassVar[float | None] = None
    retry: ClassVar[MissionRetryPolicy] = MissionRetryPolicy()

    def __init__(self, *, name: str | None = None) -> None:
        self._id = uuid4().int
        resolved_name = _default_mission_name(type(self).__name__) if name is None else name
        resolved_name = str(resolved_name).strip()
        if not resolved_name:
            raise ValueError("Mission name cannot be empty")
        self.name = resolved_name
        self._control: MissionController | None = None

    @property
    def id(self) -> int:
        return self._id

    @property
    def control(self) -> MissionController:
        if self._control is None:
            raise MissionError(
                f"Mission {self.id} is not bound to a controller"
            )
        return self._control

    def bind_control(self, control: MissionController) -> None:
        if self._control is not None and self._control is not control:
            raise MissionRegistrationError(
                f"Mission {self.id} is already bound"
            )
        self._control = control

    def unbind_control(self, control: MissionController) -> None:
        """Release a controller that currently owns this mission."""

        if self._control is control:
            self._control = None

    @property
    def stop_requested(self) -> bool:
        return self.control.stop_requested

    def checkpoint(
        self,
        name: str,
        **values: Any,
    ) -> MissionSnapshot:
        return self.control.checkpoint(name, values)

    def update_progress(
        self,
        value: float,
        *,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.control.progress(value, reason=reason)

    def complete(
        self,
        result: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot:
        return self.control.complete(result)

    def fail(
        self,
        reason: str,
        *,
        retryable: bool = False,
    ) -> MissionSnapshot:
        return self.control.fail(reason, retryable=retryable)

    def wait_for_stop(self, timeout: float | None = None) -> bool:
        return self.control.wait_for_stop(timeout)

    def stop_missions(
        self,
        *,
        tags: Iterable[str] = (),
        resources: Iterable[str] = (),
    ) -> tuple[MissionSnapshot, ...]:
        """Stop lower-authority work selected by tags or resources."""

        return self.control.stop_matching(tags=tags, resources=resources)

    @abstractmethod
    def start(self) -> None:
        """Start mission-owned work."""

    @abstractmethod
    def stop(self) -> None:
        """Release mission-owned resources safely."""

    def pause(self) -> None:
        """Pause mission work when the implementation supports it."""

    def resume(self) -> None:
        """Resume mission work when the implementation supports it."""

    def tick(self, elapsed_seconds: float) -> None:
        """Process one scheduler tick."""
