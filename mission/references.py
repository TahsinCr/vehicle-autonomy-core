"""Shared mission reference types used by orchestration components."""

from __future__ import annotations

from .base import Mission
from .execution import MissionChainSnapshot, MissionParallelSnapshot


MissionReference = Mission | int
MissionOwner = Mission | int | MissionChainSnapshot | MissionParallelSnapshot


__all__ = ["MissionOwner", "MissionReference"]
