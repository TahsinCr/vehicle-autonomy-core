"""Mission priorities, phases, policies, and event classifications."""

from __future__ import annotations

from enum import IntEnum

from ..compatibility import StrEnum

from .errors import MissionTransitionError


class MissionPriority(IntEnum):
    """Common priority bands; smaller numbers carry greater authority."""

    CRITICAL = 0
    HIGH = 100
    NORMAL = 500
    LOW = 900
    BACKGROUND = 1_000


class MissionPhase(StrEnum):
    REGISTERED = "registered"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def active(self) -> bool:
        return self in {
            MissionPhase.STARTING,
            MissionPhase.RUNNING,
            MissionPhase.PAUSING,
            MissionPhase.PAUSED,
            MissionPhase.STOPPING,
        }

    @property
    def terminal(self) -> bool:
        return self in {
            MissionPhase.STOPPED,
            MissionPhase.SUCCEEDED,
            MissionPhase.FAILED,
            MissionPhase.CANCELLED,
        }


class MissionConflictPolicy(StrEnum):
    REJECT = "reject"
    QUEUE = "queue"
    PREEMPT_LOWER = "preempt_lower"


class MissionPrerequisitePolicy(StrEnum):
    """Define what happens while required missions have not succeeded."""

    REJECT = "reject"
    QUEUE = "queue"


class ParallelFailurePolicy(StrEnum):
    """Choose how a parallel execution reacts to a failed child."""

    WAIT_ALL = "wait_all"
    CANCEL_REMAINING = "cancel_remaining"
    STOP_REMAINING = "stop_remaining"


class OwnerTerminationPolicy(StrEnum):
    """Control a background mission when its owner terminates."""

    STOP_WITH_OWNER = "stop_with_owner"
    CANCEL_WITH_OWNER = "cancel_with_owner"
    KEEP_RUNNING = "keep_running"


class BackgroundFailurePolicy(StrEnum):
    """Choose whether a background failure affects its owner execution."""

    IGNORE = "ignore"
    FAIL_OWNER = "fail_owner"
    STOP_EXECUTION = "stop_execution"


class MissionEventLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class MissionEventType(StrEnum):
    MANAGER = "manager"
    REGISTERED = "registered"
    UNREGISTERED = "unregistered"
    COMMAND = "command"
    TRANSITION = "transition"
    PROGRESS = "progress"
    CHECKPOINT = "checkpoint"
    CHAIN = "chain"
    PARALLEL = "parallel"
    BACKGROUND = "background"
    RETRY = "retry"
    LOG = "log"
    ERROR = "error"


_TRANSITIONS: dict[MissionPhase, frozenset[MissionPhase]] = {
    MissionPhase.REGISTERED: frozenset(
        {
            MissionPhase.QUEUED,
            MissionPhase.STARTING,
            MissionPhase.STOPPED,
            MissionPhase.CANCELLED,
        }
    ),
    MissionPhase.QUEUED: frozenset(
        {
            MissionPhase.STARTING,
            MissionPhase.CANCELLED,
            MissionPhase.STOPPED,
            MissionPhase.FAILED,
        }
    ),
    MissionPhase.STARTING: frozenset(
        {
            MissionPhase.RUNNING,
            MissionPhase.STOPPING,
            MissionPhase.FAILED,
            MissionPhase.CANCELLED,
        }
    ),
    MissionPhase.RUNNING: frozenset(
        {
            MissionPhase.PAUSING,
            MissionPhase.STOPPING,
            MissionPhase.SUCCEEDED,
            MissionPhase.FAILED,
            MissionPhase.CANCELLED,
        }
    ),
    MissionPhase.PAUSING: frozenset(
        {
            MissionPhase.PAUSED,
            MissionPhase.STOPPING,
            MissionPhase.FAILED,
            MissionPhase.CANCELLED,
        }
    ),
    MissionPhase.PAUSED: frozenset(
        {
            MissionPhase.RUNNING,
            MissionPhase.STOPPING,
            MissionPhase.FAILED,
            MissionPhase.CANCELLED,
        }
    ),
    MissionPhase.STOPPING: frozenset(
        {MissionPhase.STOPPED, MissionPhase.FAILED, MissionPhase.CANCELLED}
    ),
    MissionPhase.STOPPED: frozenset(
        {MissionPhase.QUEUED, MissionPhase.STARTING, MissionPhase.CANCELLED}
    ),
    MissionPhase.SUCCEEDED: frozenset(
        {MissionPhase.QUEUED, MissionPhase.STARTING}
    ),
    MissionPhase.FAILED: frozenset(
        {MissionPhase.QUEUED, MissionPhase.STARTING, MissionPhase.CANCELLED}
    ),
    MissionPhase.CANCELLED: frozenset(
        {MissionPhase.QUEUED, MissionPhase.STARTING}
    ),
}


def ensure_mission_transition(previous: MissionPhase, current: MissionPhase) -> None:
    """Raise when a mission phase change is not allowed."""

    previous = MissionPhase(previous)
    current = MissionPhase(current)
    if current not in _TRANSITIONS[previous]:
        raise MissionTransitionError(
            f"Mission transition {previous.value} -> {current.value} is not allowed"
        )
