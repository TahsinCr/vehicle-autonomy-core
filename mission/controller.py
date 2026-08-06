"""Abstract controller contract used by missions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Any

from .models import MissionSnapshot


class MissionController(ABC):
    """Base class for application-owned mission controllers."""

    @property
    @abstractmethod
    def mission_id(self) -> int:
        """Return the mission controlled by this instance."""

    @property
    @abstractmethod
    def stop_requested(self) -> bool:
        """Report whether the mission should stop its current work."""

    @abstractmethod
    def snapshot(self, mission_id: int | None = None) -> MissionSnapshot: ...

    @abstractmethod
    def snapshots(self) -> tuple[MissionSnapshot, ...]: ...

    @abstractmethod
    def wait_for_stop(self, timeout: float | None = None) -> bool: ...

    @abstractmethod
    def start(self, mission_id: int, *, reason: str = "") -> MissionSnapshot: ...

    @abstractmethod
    def pause(self, mission_id: int, *, reason: str = "") -> MissionSnapshot: ...

    @abstractmethod
    def resume(self, mission_id: int, *, reason: str = "") -> MissionSnapshot: ...

    @abstractmethod
    def stop(self, mission_id: int, *, reason: str = "") -> MissionSnapshot: ...

    @abstractmethod
    def cancel(self, mission_id: int, *, reason: str = "") -> MissionSnapshot: ...

    @abstractmethod
    def stop_matching(
        self,
        *,
        tags: Iterable[str] = (),
        resources: Iterable[str] = (),
    ) -> tuple[MissionSnapshot, ...]: ...

    @abstractmethod
    def complete(
        self,
        result: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot: ...

    @abstractmethod
    def fail(self, reason: str, *, retryable: bool = False) -> MissionSnapshot: ...

    @abstractmethod
    def progress(self, value: float, *, reason: str = "") -> MissionSnapshot: ...

    @abstractmethod
    def checkpoint(
        self,
        name: str,
        values: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot: ...
