"""Concrete mission scheduler and lifecycle engine."""

from __future__ import annotations

import math
import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..abstracts import Service
from ..compatibility import ExceptionGroup
from ..events import EventBus
from .base import Mission
from .enums import (
    BackgroundFailurePolicy,
    MissionEventLevel,
    MissionEventType,
    MissionPhase,
    OwnerTerminationPolicy,
)
from .errors import (
    MissionError,
    MissionNotFoundError,
    MissionPermissionError,
    MissionRegistrationError,
    MissionTimeoutError,
)
from .execution import (
    MissionChain,
    MissionChainSnapshot,
    MissionBackgroundSnapshot,
    MissionParallelGroup,
    MissionParallelSnapshot,
)
from .models import (
    MissionEvent,
    MissionEventQuery,
    MissionManagerSnapshot,
    MissionRetryPolicy,
    MissionSnapshot,
    MissionTransition,
)
from .lifecycle import MissionLifecycle
from .orchestration import MissionOrchestrator
from .runtime import BoundMissionController, MissionRuntime
from .scheduler import MissionScheduler


MissionReference = Mission | int
MissionFactory = Callable[[type[Mission]], Mission]


class MissionEngine(Service):
    """Run application-defined missions with scheduling and resource safety.

    Missions without conflicts run concurrently. Conflicting missions follow
    their class-level prerequisite, conflict, priority, retry, and timeout
    policies. The engine owns orchestration only; vehicle behavior stays in the
    concrete ``Mission`` subclasses supplied by the application.
    """

    def __init__(
        self,
        *,
        scheduler_interval: float = 0.05,
        stop_timeout: float = 2.0,
        event_history: int = 1_000,
        mission_factory: MissionFactory | None = None,
        lifecycle: MissionLifecycle | None = None,
        scheduler: MissionScheduler | None = None,
    ) -> None:
        scheduler_interval = float(scheduler_interval)
        stop_timeout = float(stop_timeout)
        if not math.isfinite(scheduler_interval) or scheduler_interval <= 0:
            raise ValueError("Mission scheduler interval must be positive and finite")
        if not math.isfinite(stop_timeout) or stop_timeout <= 0:
            raise ValueError("Mission stop timeout must be positive and finite")
        if lifecycle is not None and not isinstance(lifecycle, MissionLifecycle):
            raise TypeError("Mission engine lifecycle must be MissionLifecycle")
        if scheduler is not None and not isinstance(scheduler, MissionScheduler):
            raise TypeError("Mission engine scheduler must be MissionScheduler")
        self._scheduler_interval = scheduler_interval
        self._stop_timeout = stop_timeout
        self._mission_factory = mission_factory or (lambda mission_type: mission_type())
        self._runtimes: dict[int, MissionRuntime] = {}
        self._event_sequence = 0
        self._pending_transitions: deque[tuple[MissionTransition, int]] = deque()
        self._transition_publish_lock = threading.RLock()
        self._running = False
        self._closed = False
        self._scheduler_stop = threading.Event()
        self._scheduler_wake = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._condition = threading.Condition(threading.RLock())

        self.events = EventBus[MissionEvent](history=event_history)
        self.transitions = EventBus[MissionTransition](history=event_history)
        self.lifecycle = (lifecycle or MissionLifecycle()).bind(self)
        self.scheduler = (scheduler or MissionScheduler()).bind(self)
        self._orchestrator = MissionOrchestrator(self)

    @property
    def running(self) -> bool:
        with self._condition:
            return self._running

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def start(self) -> None:
        """Start queue and retry scheduling; safe to call repeatedly."""

        with self._condition:
            if self._closed:
                raise MissionError("Mission engine is closed")
            if self._running:
                return
            self._running = True
            self._scheduler_stop.clear()
            self._scheduler_wake.clear()
            thread = threading.Thread(
                target=self.scheduler._scheduler_loop,
                name="MissionScheduler",
                daemon=True,
            )
            self._scheduler_thread = thread
            thread.start()
        self._emit(MissionEventType.MANAGER, "Mission engine started")

    def stop(self) -> None:
        """Stop active work and the scheduler while keeping registrations."""

        with self._condition:
            active_ids = tuple(
                mission_id
                for mission_id, runtime in self._runtimes.items()
                if runtime.snapshot.phase.active
            )
            queued_ids = tuple(
                mission_id
                for mission_id, runtime in self._runtimes.items()
                if runtime.snapshot.phase is MissionPhase.QUEUED
            )
            thread = self._scheduler_thread
            if (
                not self._running
                and not active_ids
                and not queued_ids
                and (thread is None or not thread.is_alive())
            ):
                return
            self._running = False
            self._scheduler_stop.set()
            self._scheduler_wake.set()

        errors: list[Exception] = []
        for mission_id in active_ids:
            try:
                self.stop_mission(mission_id, reason="Mission engine stopped")
            except Exception as exc:
                errors.append(exc)
        for mission_id in queued_ids:
            try:
                self.cancel(mission_id, reason="Mission engine stopped")
            except Exception as exc:
                errors.append(exc)

        if thread is not None and thread is not threading.current_thread():
            thread.join(self._stop_timeout)
            if thread.is_alive():
                errors.append(MissionTimeoutError("Mission scheduler did not stop"))
        with self._condition:
            if (
                thread is not None
                and thread is self._scheduler_thread
                and not thread.is_alive()
            ):
                self._scheduler_thread = None
        self._emit(MissionEventType.MANAGER, "Mission engine stopped")
        if errors:
            raise ExceptionGroup("Mission engine shutdown failed", errors)

    def close(self) -> None:
        """Stop the engine, unbind missions, and close public event channels."""

        with self._condition:
            if self._closed:
                return
        self.stop()
        with self._condition:
            self._closed = True
            runtimes = tuple(self._runtimes.values())
            self._runtimes.clear()
            self._orchestrator.clear()
        for runtime in runtimes:
            runtime.mission.unbind_control(runtime.control)
        self.events.close()
        self.transitions.close()

    def launch(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.scheduler.launch(
            mission,
            requester_id=requester_id,
            reason=reason,
        )

    def run(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.launch(
            mission,
            requester_id=requester_id,
            reason=reason,
        )

    def launch_many(
        self,
        *missions: MissionReference,
    ) -> tuple[MissionSnapshot, ...]:
        return self.scheduler.launch_many(*missions)

    def run_parallel(
        self,
        *missions: MissionReference,
    ) -> tuple[MissionSnapshot, ...]:
        return self.launch_many(*missions)

    def start_chain(
        self,
        chain: MissionChain,
        *,
        input: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MissionChainSnapshot:
        """Start one isolated chain run with optional JSON-safe context data."""

        return self._orchestrator.chains.start(
            chain,
            input=input,
            metadata=metadata,
        )

    def chain_snapshot(self, chain_id: str) -> MissionChainSnapshot:
        """Return a chain run by execution ID, or the latest run by chain ID."""

        return self._orchestrator.chains.snapshot(chain_id)

    def stop_chain(self, chain_id: str) -> MissionChainSnapshot:
        """Stop a chain and propagate the command to active child missions."""

        return self._orchestrator.chains.stop(chain_id)

    def cancel_chain(self, chain_id: str) -> MissionChainSnapshot:
        """Cancel a chain and propagate cancellation to active children."""

        return self._orchestrator.chains.cancel(chain_id)

    def start_parallel(self, group: MissionParallelGroup) -> MissionParallelSnapshot:
        """Start a named, policy-controlled parallel mission group."""

        return self._orchestrator.parallel.start(group)

    def parallel_snapshot(self, group_id: str) -> MissionParallelSnapshot:
        """Return a parallel run by execution ID, or the latest run by group ID."""

        return self._orchestrator.parallel.snapshot(group_id)

    def stop_parallel(self, group_id: str) -> MissionParallelSnapshot:
        """Stop every active child in a parallel execution."""

        return self._orchestrator.parallel.stop(group_id)

    def cancel_parallel(self, group_id: str) -> MissionParallelSnapshot:
        """Cancel every active child in a parallel execution."""

        return self._orchestrator.parallel.cancel(group_id)

    def launch_background(
        self,
        mission: Mission,
        *,
        owner: Mission | int | MissionChainSnapshot | MissionParallelSnapshot,
        termination_policy: OwnerTerminationPolicy = OwnerTerminationPolicy.STOP_WITH_OWNER,
        failure_policy: BackgroundFailurePolicy = BackgroundFailurePolicy.IGNORE,
    ) -> MissionBackgroundSnapshot:
        """Launch a normal mission whose lifecycle is associated with an owner."""

        return self._orchestrator.background.launch(
            mission,
            owner=owner,
            termination_policy=termination_policy,
            failure_policy=failure_policy,
        )

    def background_snapshot(self, mission_id: int) -> MissionBackgroundSnapshot:
        """Return ownership and current lifecycle state for background work."""

        return self._orchestrator.background.snapshot(mission_id)

    def pause(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.lifecycle.pause(
            mission,
            requester_id=requester_id,
            reason=reason,
        )

    def resume(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.lifecycle.resume(
            mission,
            requester_id=requester_id,
            reason=reason,
        )

    def stop_mission(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.lifecycle.stop_mission(
            mission,
            requester_id=requester_id,
            reason=reason,
        )

    def cancel(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.lifecycle.cancel(
            mission,
            requester_id=requester_id,
            reason=reason,
        )

    def complete(
        self,
        mission: MissionReference,
        result: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot:
        return self.lifecycle.complete(mission, result)

    def fail(
        self,
        mission: MissionReference,
        reason: str,
        *,
        retryable: bool = False,
    ) -> MissionSnapshot:
        return self.lifecycle.fail(mission, reason, retryable=retryable)

    def progress(
        self,
        mission: MissionReference,
        value: float,
        *,
        reason: str = "",
    ) -> MissionSnapshot:
        return self.lifecycle.progress(mission, value, reason=reason)

    def checkpoint(
        self,
        mission: MissionReference,
        name: str,
        values: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot:
        return self.lifecycle.checkpoint(mission, name, values)

    def wait(
        self,
        mission: MissionReference,
        timeout: float | None = None,
    ) -> MissionSnapshot | None:
        return self.lifecycle.wait(mission, timeout)

    def stop_matching(
        self,
        requester_id: int,
        *,
        tags: Iterable[str] = (),
        resources: Iterable[str] = (),
    ) -> tuple[MissionSnapshot, ...]:
        return self.lifecycle.stop_matching(
            requester_id,
            tags=tags,
            resources=resources,
        )

    def register(self, mission: Mission) -> MissionSnapshot:
        if not isinstance(mission, Mission):
            raise TypeError("Mission engine can register Mission instances only")
        self._validate_mission(mission)
        with self._condition:
            if self._closed:
                raise MissionError("Mission engine is closed")
            if mission.id in self._runtimes:
                raise MissionRegistrationError(
                    f"Mission {mission.id} is already registered"
                )
            control = BoundMissionController(self, mission.id)
            mission.bind_control(control)
            snapshot = MissionSnapshot(mission.id, mission.name)
            self._runtimes[mission.id] = MissionRuntime(
                mission=mission,
                snapshot=snapshot,
                stop_event=threading.Event(),
                control=control,
            )
            self._condition.notify_all()
        self._emit(
            MissionEventType.REGISTERED,
            f"Mission registered: {mission.name}",
            mission_id=mission.id,
        )
        return snapshot

    def unregister(self, mission: MissionReference) -> bool:
        mission_id = self._mission_id(mission)
        with self._condition:
            runtime = self._runtimes.get(mission_id)
            if runtime is None:
                return False
            if runtime.snapshot.phase.active or runtime.snapshot.phase is MissionPhase.QUEUED:
                raise MissionRegistrationError(
                    f"Active or queued mission {mission_id} cannot be unregistered"
                )
            self._runtimes.pop(mission_id)
            self._orchestrator.forget_mission(mission_id)
        runtime.mission.unbind_control(runtime.control)
        self._emit(
            MissionEventType.UNREGISTERED,
            f"Mission unregistered: {runtime.mission.name}",
            mission_id=mission_id,
        )
        return True

    def mission(self, mission: MissionReference) -> Mission:
        return self._runtime(mission).mission

    def snapshot(self, mission: MissionReference) -> MissionSnapshot:
        with self._condition:
            return self._runtime_locked(self._mission_id(mission)).snapshot

    def snapshots(self) -> tuple[MissionSnapshot, ...]:
        with self._condition:
            return tuple(
                runtime.snapshot
                for runtime in sorted(
                    self._runtimes.values(),
                    key=lambda item: item.snapshot.registered_at,
                )
            )

    def manager_snapshot(self) -> MissionManagerSnapshot:
        with self._condition:
            snapshots = tuple(runtime.snapshot for runtime in self._runtimes.values())
            owners = {
                resource: runtime.mission.id
                for runtime in self._runtimes.values()
                if runtime.snapshot.phase.active
                for resource in runtime.mission.resources
            }
        return MissionManagerSnapshot(
            running=self._running,
            registered_missions=tuple(item.mission_id for item in snapshots),
            active_missions=tuple(
                item.mission_id for item in snapshots if item.phase.active
            ),
            queued_missions=tuple(
                item.mission_id
                for item in snapshots
                if item.phase is MissionPhase.QUEUED
            ),
            paused_missions=tuple(
                item.mission_id
                for item in snapshots
                if item.phase is MissionPhase.PAUSED
            ),
            resource_owners=owners,
        )

    @staticmethod
    def _validate_mission(mission: Mission) -> None:
        if isinstance(mission.priority, bool) or not isinstance(mission.priority, int):
            raise MissionRegistrationError("Mission priority must be an integer")
        for name, value in (
            ("tick_interval", mission.tick_interval),
            ("timeout_seconds", mission.timeout_seconds),
            ("queue_timeout_seconds", mission.queue_timeout_seconds),
        ):
            if value is None:
                continue
            normalized = float(value)
            if not math.isfinite(normalized) or normalized <= 0:
                raise MissionRegistrationError(
                    f"Mission {name} must be positive and finite"
                )
        if not isinstance(mission.retry, MissionRetryPolicy):
            raise MissionRegistrationError("Mission retry must be MissionRetryPolicy")
        for name, values in (
            ("resources", mission.resources),
            ("tags", mission.tags),
        ):
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise MissionRegistrationError(
                    f"Mission {name} must contain non-empty strings"
                )
        for name, mission_types in (
            ("blocks", mission.blocks),
            ("prerequisites", mission.prerequisites),
        ):
            if any(
                not isinstance(mission_type, type)
                or not issubclass(mission_type, Mission)
                for mission_type in mission_types
            ):
                raise MissionRegistrationError(
                    f"Mission {name} must contain Mission subclasses"
                )

    def query_events(
        self,
        query: MissionEventQuery | None = None,
    ) -> tuple[MissionEvent, ...]:
        query = query or MissionEventQuery()
        return self.events.query(predicate=query.matches, limit=query.limit)

    def _authorize_locked(
        self,
        requester_id: int | None,
        target: MissionRuntime,
    ) -> None:
        if requester_id is None or requester_id == target.mission.id:
            return
        requester = self._runtime_locked(requester_id)
        if requester.mission.priority > target.mission.priority:
            raise MissionPermissionError(
                f"Mission {requester_id} has insufficient priority over {target.mission.id}"
            )

    def _matching_active(
        self,
        requester_id: int,
        *,
        tags: Iterable[str],
        resources: Iterable[str],
    ) -> tuple[int, ...]:
        required_tags = frozenset(str(value) for value in tags)
        required_resources = frozenset(str(value) for value in resources)
        with self._condition:
            requester = self._runtime_locked(requester_id)
            targets = tuple(
                runtime.mission.id
                for runtime in self._runtimes.values()
                if runtime.mission.id != requester_id
                and runtime.snapshot.phase.active
                and (not required_tags or required_tags & runtime.mission.tags)
                and (
                    not required_resources
                    or required_resources & runtime.mission.resources
                )
                and requester.mission.priority <= runtime.mission.priority
            )
        return targets

    def _conflict_message(
        self,
        runtime: MissionRuntime,
        conflicts: tuple[MissionRuntime, ...],
    ) -> str:
        names = ", ".join(item.mission.name for item in conflicts)
        return f"Mission {runtime.mission.name} conflicts with: {names}"

    def _emit(
        self,
        event_type: MissionEventType,
        message: str,
        *,
        level: MissionEventLevel = MissionEventLevel.INFO,
        mission_id: int | None = None,
        requester_id: int | None = None,
        generation: int = 0,
        fields: Mapping[str, Any] | None = None,
    ) -> MissionEvent:
        with self._condition:
            self._event_sequence += 1
            event = MissionEvent(
                event_type,
                message,
                level,
                mission_id,
                requester_id,
                generation,
                dict(fields or {}),
                self._event_sequence,
            )
        if not self.events.closed:
            self.events.publish(event)
        return event

    def _mission_id(self, mission: MissionReference) -> int:
        return mission.id if isinstance(mission, Mission) else int(mission)

    def _runtime(self, mission: MissionReference) -> MissionRuntime:
        with self._condition:
            return self._runtime_locked(self._mission_id(mission))

    def _runtime_locked(self, mission_id: int) -> MissionRuntime:
        try:
            return self._runtimes[mission_id]
        except KeyError as exc:
            raise MissionNotFoundError(f"Mission not found: {mission_id}") from exc

    def _stop_requested(self, mission_id: int) -> bool:
        return self._runtime(mission_id).stop_event.is_set()

    def _wait_for_stop(self, mission_id: int, timeout: float | None) -> bool:
        return self._runtime(mission_id).stop_event.wait(timeout)

    def __enter__(self) -> "MissionEngine":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
