"""Public mission contracts and lifecycle API."""

# Default unittest discovery briefly imports source directories as top-level
# packages. The supported package is <parent>.core.mission, so defer eager
# imports only for that discovery probe.
if __package__ == "mission":
    __all__: list[str] = []
else:
    from .base import Mission
    from .controller import MissionController
    from .engine import MissionEngine
    from .lifecycle import MissionLifecycle
    from .scheduler import MissionScheduler
    from .enums import (
        BackgroundFailurePolicy,
        MissionConflictPolicy,
        MissionEventLevel,
        MissionEventType,
        MissionPhase,
        MissionPrerequisitePolicy,
        MissionPriority,
        OwnerTerminationPolicy,
        ParallelFailurePolicy,
        ensure_mission_transition,
    )
    from .errors import (
        MissionConflictError,
        MissionError,
        MissionNotFoundError,
        MissionPermissionError,
        MissionRegistrationError,
        MissionTransitionError,
        MissionTimeoutError,
    )
    from .execution import (
        MissionChain,
        MissionChainSnapshot,
        MissionBackgroundSnapshot,
        MissionExecutionContext,
        MissionExecutionResult,
        MissionNode,
        MissionParallelGroup,
        MissionParallelSnapshot,
        MissionParallelStage,
    )
    from .models import (
        MissionEvent,
        MissionEventQuery,
        MissionManagerSnapshot,
        MissionRetryPolicy,
        MissionSnapshot,
        MissionTransition,
    )
    __all__ = [
        "BackgroundFailurePolicy",
        "Mission",
        "MissionBackgroundSnapshot",
        "MissionChain",
        "MissionChainSnapshot",
        "MissionConflictError",
        "MissionConflictPolicy",
        "MissionController",
        "MissionError",
        "MissionEngine",
        "MissionExecutionContext",
        "MissionExecutionResult",
        "MissionLifecycle",
        "MissionEvent",
        "MissionEventLevel",
        "MissionEventQuery",
        "MissionEventType",
        "MissionManagerSnapshot",
        "MissionNode",
        "MissionNotFoundError",
        "MissionPermissionError",
        "MissionPhase",
        "MissionPrerequisitePolicy",
        "MissionPriority",
        "MissionParallelGroup",
        "MissionParallelSnapshot",
        "MissionParallelStage",
        "MissionRegistrationError",
        "MissionRetryPolicy",
        "MissionSnapshot",
        "MissionScheduler",
        "MissionTransition",
        "MissionTransitionError",
        "MissionTimeoutError",
        "OwnerTerminationPolicy",
        "ParallelFailurePolicy",
        "ensure_mission_transition",
    ]
