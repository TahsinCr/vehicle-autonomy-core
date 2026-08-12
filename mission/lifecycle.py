"""Ready-to-use mission lifecycle component."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from .base import Mission
from .enums import MissionEventType, MissionPhase, ensure_mission_transition
from .errors import MissionTimeoutError, MissionTransitionError
from .models import MissionSnapshot, MissionTransition
from .runtime import MissionRuntime

if TYPE_CHECKING:
    from .engine import MissionEngine


MissionReference = Mission | int


class MissionLifecycle:
    """Manage mission commands and transitions for one bound engine.

    ``MissionEngine`` creates and binds this component by default. Applications
    can pass a subclass instance to the engine when lifecycle behavior needs a
    focused extension without subclassing the complete engine.
    """

    def __init__(self, engine: "MissionEngine | None" = None) -> None:
        self._engine: MissionEngine | None = None
        if engine is not None:
            self.bind(engine)

    @property
    def engine(self) -> "MissionEngine":
        if self._engine is None:
            raise RuntimeError("Mission lifecycle is not bound to an engine")
        return self._engine

    def bind(self, engine: "MissionEngine") -> "MissionLifecycle":
        """Bind this component to one engine; repeated binding is idempotent."""

        from .engine import MissionEngine

        if not isinstance(engine, MissionEngine):
            raise TypeError("Mission lifecycle requires a MissionEngine")
        if self._engine is not None and self._engine is not engine:
            raise RuntimeError("Mission lifecycle is already bound to another engine")
        self._engine = engine
        return self

    def pause(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        runtime = self.engine._runtime(mission)
        transition: MissionTransition | None = None
        with self.engine._condition:
            self.engine._authorize_locked(requester_id, runtime)
            if runtime.snapshot.phase is MissionPhase.PAUSED:
                return runtime.snapshot
            _, transition = self._transition_locked(
                runtime,
                MissionPhase.PAUSING,
                reason=reason,
                requester_id=requester_id,
            )
        self._publish_transition(transition)
        try:
            with runtime.callback_lock:
                with self.engine._condition:
                    if runtime.snapshot.phase is not MissionPhase.PAUSING:
                        return runtime.snapshot
                runtime.mission.pause()
        except Exception as exc:
            return self.fail(runtime.mission.id, str(exc))
        with self.engine._condition:
            if runtime.snapshot.phase is not MissionPhase.PAUSING:
                return runtime.snapshot
            snapshot, transition = self._transition_locked(
                runtime,
                MissionPhase.PAUSED,
                reason=reason,
                requester_id=requester_id,
            )
        self._publish_transition(transition)
        return snapshot

    def resume(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        runtime = self.engine._runtime(mission)
        with self.engine._condition:
            self.engine._authorize_locked(requester_id, runtime)
            if runtime.snapshot.phase is MissionPhase.RUNNING:
                return runtime.snapshot
            if runtime.snapshot.phase is not MissionPhase.PAUSED:
                raise MissionTransitionError("Only a paused mission can resume")
        try:
            with runtime.callback_lock:
                with self.engine._condition:
                    if runtime.snapshot.phase is not MissionPhase.PAUSED:
                        return runtime.snapshot
                runtime.mission.resume()
        except Exception as exc:
            return self.fail(runtime.mission.id, str(exc))
        with self.engine._condition:
            if runtime.snapshot.phase is not MissionPhase.PAUSED:
                return runtime.snapshot
            snapshot, transition = self._transition_locked(
                runtime,
                MissionPhase.RUNNING,
                reason=reason,
                requester_id=requester_id,
            )
        self._publish_transition(transition)
        return snapshot

    def stop_mission(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self._finish_by_command(
            mission,
            MissionPhase.STOPPED,
            requester_id=requester_id,
            reason=reason or "Mission stopped",
        )

    def cancel(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        return self._finish_by_command(
            mission,
            MissionPhase.CANCELLED,
            requester_id=requester_id,
            reason=reason or "Mission cancelled",
        )

    def complete(
        self,
        mission: MissionReference,
        result: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot:
        runtime = self.engine._runtime(mission)
        with self.engine._condition:
            if runtime.snapshot.phase is MissionPhase.SUCCEEDED:
                return runtime.snapshot
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            runtime.stop_event.set()
        try:
            self._join_worker(runtime)
            self._cleanup_runtime(runtime)
        except Exception as exc:
            return self.fail(runtime.mission.id, f"Mission cleanup failed: {exc}")
        with self.engine._condition:
            if runtime.snapshot.phase is MissionPhase.STOPPING:
                return runtime.snapshot
            snapshot, transition = self._transition_locked(
                runtime,
                MissionPhase.SUCCEEDED,
                result=dict(result or {}),
                progress=1.0,
                reason="Mission completed",
            )
        self._publish_transition(transition)
        self.engine.scheduler._after_terminal(runtime.mission.id, succeeded=True)
        return snapshot

    def fail(
        self,
        mission: MissionReference,
        reason: str,
        *,
        retryable: bool = False,
    ) -> MissionSnapshot:
        runtime = self.engine._runtime(mission)
        failure_reason = str(reason).strip() or "Mission failed"
        with self.engine._condition:
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            runtime.stop_event.set()
        try:
            self._join_worker(runtime)
            self._cleanup_runtime(runtime)
        except Exception as exc:
            failure_reason = f"{failure_reason}; cleanup failed: {exc}"
        with self.engine._condition:
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            snapshot, transition = self._transition_locked(
                runtime,
                MissionPhase.FAILED,
                reason=failure_reason,
            )
            should_retry = (
                retryable and snapshot.attempt < runtime.mission.retry.attempts
            )
            if should_retry:
                snapshot, queued_transition = self._queue_locked(
                    runtime,
                    "Mission queued for retry",
                    next_retry_at=time.time() + runtime.mission.retry.delay,
                )
            else:
                queued_transition = None
        self._publish_transition(transition)
        self._publish_transition(queued_transition)
        if not should_retry:
            self.engine.scheduler._after_terminal(runtime.mission.id, succeeded=False)
        else:
            self.engine._emit(
                MissionEventType.RETRY,
                "Mission retry scheduled",
                mission_id=runtime.mission.id,
                fields={"attempt": snapshot.attempt, "at": snapshot.next_retry_at},
            )
            self.engine._scheduler_wake.set()
        return snapshot

    def progress(
        self,
        mission: MissionReference,
        value: float,
        *,
        reason: str = "",
    ) -> MissionSnapshot:
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Mission progress must be between zero and one")
        with self.engine._condition:
            runtime = self.engine._runtime_locked(self.engine._mission_id(mission))
            if not runtime.snapshot.phase.active:
                raise MissionTransitionError("Inactive mission progress cannot change")
            runtime.snapshot = runtime.snapshot.evolve(progress=value, reason=reason)
            snapshot = runtime.snapshot
            self.engine._condition.notify_all()
        self.engine._emit(
            MissionEventType.PROGRESS,
            reason or f"Mission progress: {value:.0%}",
            mission_id=snapshot.mission_id,
            generation=snapshot.generation,
            fields={"progress": value},
        )
        return snapshot

    def checkpoint(
        self,
        mission: MissionReference,
        name: str,
        values: Mapping[str, Any] | None = None,
    ) -> MissionSnapshot:
        name = str(name).strip()
        if not name:
            raise ValueError("Mission checkpoint name cannot be empty")
        with self.engine._condition:
            runtime = self.engine._runtime_locked(self.engine._mission_id(mission))
            checkpoints = dict(runtime.snapshot.checkpoints)
            checkpoints[name] = dict(values or {})
            runtime.snapshot = runtime.snapshot.evolve(checkpoints=checkpoints)
            snapshot = runtime.snapshot
            self.engine._condition.notify_all()
        self.engine._emit(
            MissionEventType.CHECKPOINT,
            f"Mission checkpoint: {name}",
            mission_id=snapshot.mission_id,
            generation=snapshot.generation,
            fields={"name": name, **dict(values or {})},
        )
        return snapshot

    def wait(
        self,
        mission: MissionReference,
        timeout: float | None = None,
    ) -> MissionSnapshot | None:
        mission_id = self.engine._mission_id(mission)
        with self.engine._condition:
            self.engine._runtime_locked(mission_id)
            ready = self.engine._condition.wait_for(
                lambda: self.engine._runtime_locked(mission_id).snapshot.phase.terminal,
                timeout=timeout,
            )
            return self.engine._runtime_locked(mission_id).snapshot if ready else None

    def stop_matching(
        self,
        requester_id: int,
        *,
        tags: Iterable[str] = (),
        resources: Iterable[str] = (),
    ) -> tuple[MissionSnapshot, ...]:
        """Let one mission stop authorized active work without direct references."""

        targets = self.engine._matching_active(
            requester_id,
            tags=tags,
            resources=resources,
        )
        return tuple(
            self.stop_mission(
                mission_id,
                requester_id=requester_id,
                reason=f"Stopped by mission {requester_id}",
            )
            for mission_id in targets
        )

    def _run_mission(self, mission_id: int, generation: int) -> None:
        runtime = self.engine._runtime(mission_id)
        try:
            with runtime.callback_lock:
                with self.engine._condition:
                    if (
                        runtime.snapshot.generation != generation
                        or runtime.snapshot.phase is not MissionPhase.STARTING
                    ):
                        return
                    _, transition = self._transition_locked(
                        runtime, MissionPhase.RUNNING
                    )
                self._publish_transition(transition)
                with self.engine._condition:
                    if (
                        runtime.snapshot.generation != generation
                        or runtime.snapshot.phase is not MissionPhase.RUNNING
                    ):
                        return
                runtime.mission.start()
            while not runtime.stop_event.wait(runtime.mission.tick_interval):
                with self.engine._condition:
                    snapshot = runtime.snapshot
                    elapsed = self._active_elapsed_locked(runtime)
                if snapshot.generation != generation or snapshot.phase.terminal:
                    break
                if snapshot.phase is not MissionPhase.RUNNING:
                    continue
                timeout = runtime.mission.timeout_seconds
                if timeout is not None and elapsed >= timeout:
                    self.fail(mission_id, "Mission execution timed out", retryable=True)
                    break
                with runtime.callback_lock:
                    with self.engine._condition:
                        if (
                            runtime.snapshot.generation != generation
                            or runtime.snapshot.phase is not MissionPhase.RUNNING
                        ):
                            continue
                        elapsed = self._active_elapsed_locked(runtime)
                    runtime.mission.tick(elapsed)
        except Exception as exc:
            self.fail(mission_id, str(exc), retryable=True)

    def _finish_by_command(
        self,
        mission: MissionReference,
        terminal: MissionPhase,
        *,
        requester_id: int | None,
        reason: str,
    ) -> MissionSnapshot:
        runtime = self.engine._runtime(mission)
        transition: MissionTransition | None = None
        with self.engine._condition:
            self.engine._authorize_locked(requester_id, runtime)
            current = runtime.snapshot.phase
            if current is terminal:
                return runtime.snapshot
            if current.terminal:
                return runtime.snapshot
            runtime.stop_event.set()
            if current is MissionPhase.QUEUED:
                snapshot, transition = self._transition_locked(
                    runtime,
                    terminal,
                    requester_id=requester_id,
                    reason=reason,
                )
            elif current is MissionPhase.STOPPING:
                snapshot = runtime.snapshot
            else:
                _, transition = self._transition_locked(
                    runtime,
                    MissionPhase.STOPPING,
                    requester_id=requester_id,
                    reason=reason,
                )

        self._publish_transition(transition)

        if current is not MissionPhase.QUEUED:
            self._join_worker(runtime)
            try:
                self._cleanup_runtime(runtime)
            except Exception as exc:
                return self.fail(runtime.mission.id, str(exc))
            with self.engine._condition:
                if runtime.snapshot.phase is MissionPhase.STOPPING:
                    snapshot, transition = self._transition_locked(
                        runtime,
                        terminal,
                        requester_id=requester_id,
                        reason=reason,
                    )
                else:
                    snapshot = runtime.snapshot
                    transition = None
            self._publish_transition(transition)
        self.engine.scheduler._after_terminal(runtime.mission.id, succeeded=False)
        self.engine._scheduler_wake.set()
        return snapshot

    def _join_worker(self, runtime: MissionRuntime) -> None:
        worker = runtime.worker
        if worker is None or worker is threading.current_thread():
            return
        worker.join(self.engine._stop_timeout)
        if worker.is_alive():
            raise MissionTimeoutError(
                f"Mission {runtime.mission.id} did not stop in time"
            )

    @staticmethod
    def _cleanup_runtime(runtime: MissionRuntime) -> None:
        with runtime.cleanup_lock:
            if runtime.cleaned:
                return
            with runtime.callback_lock:
                runtime.mission.stop()
                runtime.cleaned = True

    def _transition_locked(
        self,
        runtime: MissionRuntime,
        current: MissionPhase,
        *,
        requester_id: int | None = None,
        reason: str = "",
        result: Mapping[str, Any] | None = None,
        progress: float | None = None,
    ) -> tuple[MissionSnapshot, MissionTransition]:
        previous = runtime.snapshot.phase
        ensure_mission_transition(previous, current)
        now = time.time()
        changes: dict[str, Any] = {
            "phase": current,
            "reason": reason,
            "updated_at": now,
        }
        if current is MissionPhase.QUEUED:
            changes["queued_at"] = now
        if current is MissionPhase.STARTING:
            changes.update(
                generation=runtime.snapshot.generation + 1,
                attempt=runtime.snapshot.attempt + 1,
                started_at=now,
                finished_at=None,
                next_retry_at=None,
                progress=0.0,
                result={},
            )
            runtime.active_elapsed = 0.0
            runtime.active_started_monotonic = None
        if current is MissionPhase.RUNNING:
            runtime.active_started_monotonic = time.monotonic()
        elif previous is MissionPhase.RUNNING:
            runtime.active_elapsed = self._active_elapsed_locked(runtime)
            runtime.active_started_monotonic = None
        if current.terminal:
            changes["finished_at"] = now
        if result is not None:
            changes["result"] = dict(result)
        if progress is not None:
            changes["progress"] = progress
        runtime.snapshot = runtime.snapshot.evolve(**changes)
        transition = MissionTransition(
            runtime.mission.id,
            previous,
            current,
            requester_id,
            reason,
        )
        self.engine._pending_transitions.append(
            (transition, runtime.snapshot.generation)
        )
        self.engine._condition.notify_all()
        return runtime.snapshot, transition

    def _publish_transition(self, transition: MissionTransition | None) -> None:
        if transition is None:
            return
        with self.engine._transition_publish_lock:
            while True:
                with self.engine._condition:
                    if not self.engine._pending_transitions:
                        return
                    current, generation = self.engine._pending_transitions.popleft()
                self.engine.transitions.publish(current)
                self.engine._emit(
                    MissionEventType.TRANSITION,
                    f"Mission {current.previous.value} -> {current.current.value}",
                    mission_id=current.mission_id,
                    requester_id=current.requester_id,
                    generation=generation,
                    fields={
                        "previous": current.previous.value,
                        "current": current.current.value,
                    },
                )

    @staticmethod
    def _active_elapsed_locked(runtime: MissionRuntime) -> float:
        elapsed = runtime.active_elapsed
        if runtime.active_started_monotonic is not None:
            elapsed += time.monotonic() - runtime.active_started_monotonic
        return elapsed

    def _queue_locked(
        self,
        runtime: MissionRuntime,
        reason: str,
        *,
        next_retry_at: float | None = None,
    ) -> tuple[MissionSnapshot, MissionTransition | None]:
        if runtime.snapshot.phase is MissionPhase.QUEUED:
            if next_retry_at is not None:
                runtime.snapshot = runtime.snapshot.evolve(next_retry_at=next_retry_at)
            return runtime.snapshot, None
        snapshot, transition = self._transition_locked(
            runtime,
            MissionPhase.QUEUED,
            reason=reason,
        )
        if next_retry_at is not None:
            runtime.snapshot = snapshot.evolve(next_retry_at=next_retry_at)
            snapshot = runtime.snapshot
        self.engine._scheduler_wake.set()
        return snapshot, transition
