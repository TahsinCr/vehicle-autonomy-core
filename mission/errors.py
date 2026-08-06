"""Mission lifecycle and coordination exceptions."""

from __future__ import annotations


class MissionError(RuntimeError):
    """Base error for mission lifecycle and coordination failures."""


class MissionRegistrationError(MissionError):
    """Raised when a mission definition is invalid or already registered."""


class MissionPermissionError(MissionError):
    """Raised when one mission has insufficient authority over another."""


class MissionConflictError(MissionError):
    """Raised when active missions or exclusive resources conflict."""


class MissionTransitionError(MissionError):
    """Raised when a mission lifecycle transition is not valid."""


class MissionNotFoundError(MissionError, LookupError):
    """Raised when a mission ID is not registered in the engine."""


class MissionTimeoutError(MissionError, TimeoutError):
    """Raised when mission-owned work does not stop in time."""
