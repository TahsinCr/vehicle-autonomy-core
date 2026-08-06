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
        MissionConflictPolicy,
        MissionEventLevel,
        MissionEventType,
        MissionPhase,
        MissionPrerequisitePolicy,
        MissionPriority,
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
    from .models import (
        MissionChain,
        MissionChainSnapshot,
        MissionEvent,
        MissionEventQuery,
        MissionManagerSnapshot,
        MissionRetryPolicy,
        MissionSnapshot,
        MissionTransition,
    )
    # Preserve the historical public module identity for introspection and pickle
    # compatibility while implementations live in focused submodules.
    for _public_object in (
        Mission,
        MissionChain,
        MissionChainSnapshot,
        MissionConflictError,
        MissionConflictPolicy,
        MissionController,
        MissionError,
        MissionEngine,
        MissionLifecycle,
        MissionEvent,
        MissionEventLevel,
        MissionEventQuery,
        MissionEventType,
        MissionManagerSnapshot,
        MissionNotFoundError,
        MissionPermissionError,
        MissionPhase,
        MissionPrerequisitePolicy,
        MissionPriority,
        MissionRegistrationError,
        MissionRetryPolicy,
        MissionSnapshot,
        MissionScheduler,
        MissionTransition,
        MissionTransitionError,
        MissionTimeoutError,
        ensure_mission_transition,
    ):
        _public_object.__module__ = __name__
    del _public_object


    __all__ = [
        "Mission",
        "MissionChain",
        "MissionChainSnapshot",
        "MissionConflictError",
        "MissionConflictPolicy",
        "MissionController",
        "MissionError",
        "MissionEngine",
        "MissionLifecycle",
        "MissionEvent",
        "MissionEventLevel",
        "MissionEventQuery",
        "MissionEventType",
        "MissionManagerSnapshot",
        "MissionNotFoundError",
        "MissionPermissionError",
        "MissionPhase",
        "MissionPrerequisitePolicy",
        "MissionPriority",
        "MissionRegistrationError",
        "MissionRetryPolicy",
        "MissionSnapshot",
        "MissionScheduler",
        "MissionTransition",
        "MissionTransitionError",
        "MissionTimeoutError",
        "ensure_mission_transition",
    ]
