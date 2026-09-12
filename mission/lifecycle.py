"""Ready-to-use mission lifecycle component."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from ..abstracts import _freeze_model_value
from .base import Mission
from .enums import MissionEventType, MissionPhase, ensure_mission_transition
from .errors import (
    MissionCleanupError,
    MissionConflictError,
    MissionTimeoutError,
    MissionTransitionError,
)
from .models import MissionSnapshot, MissionTransition
from .runtime import MissionRuntime, PendingTerminalIntent

if TYPE_CHECKING:
    from .engine import MissionEngine


MissionReference = Mission | int


class _MissionExit(BaseException):
    """Unwind a mission callback before publishing its terminal state."""

    def __init__(self, intent: PendingTerminalIntent) -> None:
        self.intent = intent


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
        snapshot = runtime.snapshot
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
        stopping_transition: MissionTransition | None = None
        with self.engine._condition:
            if runtime.snapshot.phase is MissionPhase.SUCCEEDED:
                return runtime.snapshot
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            if (
                runtime.snapshot.phase is MissionPhase.STOPPING
                and runtime.cleanup_error is not None
            ):
                if (
                    runtime.pending_terminal is not None
                    and runtime.pending_terminal.phase is not MissionPhase.SUCCEEDED
                ):
                    raise MissionTransitionError(
                        "Mission already has a different terminal intent"
                    )
                retry_cleanup = True
            elif runtime.snapshot.phase is not MissionPhase.RUNNING:
                raise MissionTransitionError(
                    "Only a running mission can complete"
                )
            else:
                retry_cleanup = False
            runtime.stop_event.set()
            if not retry_cleanup:
                _, stopping_transition = self._transition_locked(
                    runtime,
                    MissionPhase.STOPPING,
                    reason="Mission completion requested",
                )
                intent = self._set_terminal_intent_locked(
                    runtime,
                    MissionPhase.SUCCEEDED,
                    result=result,
                    transition=stopping_transition,
                )
            else:
                intent = runtime.pending_terminal
            if (
                runtime.worker is threading.current_thread()
                and intent is not None
            ):
                raise _MissionExit(intent)
        self._publish_intent_transition(intent)
        if retry_cleanup and intent is not None:
            return self.retry_cleanup(runtime.mission.id)
        if intent is None:
            raise MissionTransitionError("Mission completion intent is missing")
        return self._finalize_pending_terminal(runtime, intent)

    def _complete_stopping(
        self,
        runtime: MissionRuntime,
        result: Mapping[str, Any] | None,
        *,
        cleanup: bool = True,
        intent: PendingTerminalIntent | None = None,
    ) -> MissionSnapshot:
        self._join_worker(runtime)
        if cleanup:
            self._cleanup_or_raise(runtime)
        with self.engine._condition:
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            if intent is not None and runtime.pending_terminal is not intent:
                raise MissionTransitionError("Mission terminal intent changed")
            snapshot, transition = self._transition_locked(
                runtime,
                MissionPhase.SUCCEEDED,
                result=dict(result or {}),
                progress=1.0,
                reason="Mission completed",
            )
            if intent is not None:
                runtime.pending_terminal = None
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
        stopping_transition: MissionTransition | None = None
        with self.engine._condition:
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            if runtime.snapshot.phase is MissionPhase.STOPPING and runtime.pending_terminal is not None:
                if runtime.pending_terminal.phase is not MissionPhase.FAILED:
                    raise MissionTransitionError(
                        "Mission already has a different terminal intent"
                    )
            runtime.stop_event.set()
            if (
                runtime.snapshot.phase.active
                and runtime.snapshot.phase is not MissionPhase.STOPPING
            ):
                _, stopping_transition = self._transition_locked(
                    runtime,
                    MissionPhase.STOPPING,
                    reason=failure_reason,
                )
                intent = self._set_terminal_intent_locked(
                    runtime,
                    MissionPhase.FAILED,
                    reason=failure_reason,
                    retryable=retryable,
                    transition=stopping_transition,
                )
            else:
                intent = runtime.pending_terminal
                if intent is None:
                    intent = self._set_terminal_intent_locked(
                        runtime,
                        MissionPhase.FAILED,
                        reason=failure_reason,
                        retryable=retryable,
                        transition=stopping_transition,
                    )
            if runtime.worker is threading.current_thread():
                if intent is None:
                    raise MissionTransitionError("Mission failure intent is missing")
                raise _MissionExit(intent)
        self._publish_intent_transition(intent)
        if intent is None:
            raise MissionTransitionError("Mission failure intent is missing")
        return self._finalize_pending_terminal(runtime, intent)

    def _finish_failure(
        self,
        runtime: MissionRuntime,
        reason: str,
        retryable: bool,
        *,
        cleanup: bool = True,
        intent: PendingTerminalIntent | None = None,
    ) -> MissionSnapshot:
        if cleanup:
            self._cleanup_or_raise(runtime)
        with self.engine._condition:
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            if intent is not None and runtime.pending_terminal is not intent:
                raise MissionTransitionError("Mission terminal intent changed")
            snapshot, transition = self._transition_locked(
                runtime,
                MissionPhase.FAILED,
                reason=reason,
            )
            retry_available = (
                retryable and snapshot.attempt < runtime.mission.retry.attempts
            )
            queue_limit = self.engine._max_queued_missions
            queue_has_capacity = (
                queue_limit is None or len(self.engine._queued_ids) < queue_limit
            )
            should_retry = retry_available and queue_has_capacity
            retry_rejected = retry_available and not queue_has_capacity
            if should_retry:
                retry_delay = runtime.mission.retry.delay
                snapshot, queued_transition = self._queue_locked(
                    runtime,
                    "Mission queued for retry",
                    next_retry_at=time.time() + retry_delay,
                    next_retry_monotonic=time.monotonic() + retry_delay,
                )
            else:
                queued_transition = None
            if intent is not None:
                runtime.pending_terminal = None
        self._publish_transition(transition)
        self._publish_transition(queued_transition)
        if not should_retry:
            self.engine.scheduler._after_terminal(runtime.mission.id, succeeded=False)
            if retry_rejected:
                self.engine._emit(
                    MissionEventType.ERROR,
                    "Mission retry rejected because queue capacity was reached",
                    mission_id=runtime.mission.id,
                )
        else:
            self.engine._emit(
                MissionEventType.RETRY,
                "Mission retry scheduled",
                mission_id=runtime.mission.id,
                fields={"attempt": snapshot.attempt, "at": snapshot.next_retry_at},
            )
            self.engine._scheduler_wake.set()
        return snapshot

    def retry_cleanup(self, mission: MissionReference) -> MissionSnapshot:
        """Retry failed cleanup and preserve the mission's terminal intent."""

        runtime = self.engine._runtime(mission)
        with self.engine._condition:
            intent = runtime.pending_terminal
            if runtime.snapshot.phase is not MissionPhase.STOPPING:
                raise MissionTransitionError("Mission is not waiting for cleanup")
            if runtime.cleanup_error is None:
                raise MissionTransitionError("Mission cleanup has not failed")
            if intent is None:
                raise MissionTransitionError(
                    "Mission has no pending terminal intent; retry its stop or cancel command"
                )
        return self._finalize_pending_terminal(runtime, intent, retry_cleanup=True)

    def _set_terminal_intent_locked(
        self,
        runtime: MissionRuntime,
        phase: MissionPhase,
        *,
        result: Mapping[str, Any] | None = None,
        reason: str = "",
        retryable: bool = False,
        requester_id: int | None = None,
        transition: MissionTransition | None = None,
    ) -> PendingTerminalIntent:
        if runtime.pending_terminal is not None:
            raise MissionTransitionError("Mission already has a terminal intent")
        intent = PendingTerminalIntent(
            generation=runtime.snapshot.generation,
            phase=phase,
            result=None if result is None else _freeze_model_value(result),
            reason=reason,
            retryable=retryable,
            requester_id=requester_id,
            transition=transition,
        )
        runtime.pending_terminal = intent
        return intent

    def _publish_intent_transition(
        self,
        intent: PendingTerminalIntent | None,
    ) -> None:
        if intent is None:
            return
        with self.engine._condition:
            transition = intent.transition
            intent.transition = None
        self._publish_transition(transition)

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
            if runtime.snapshot.phase.terminal:
                raise MissionTransitionError(
                    "Terminal mission checkpoint cannot change"
                )
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
            fields={**dict(values or {}), "name": name},
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
                    if (
                        runtime.activation_guard is not None
                        and not runtime.activation_guard()
                    ):
                        runtime.activation_guard = None
                        runtime.stop_event.set()
                        _, transition = self._transition_locked(
                            runtime,
                            MissionPhase.STOPPING,
                            reason="Mission activation guard rejected startup",
                        )
                        intent = self._set_terminal_intent_locked(
                            runtime,
                            MissionPhase.CANCELLED,
                            reason="Mission activation guard rejected startup",
                            transition=transition,
                        )
                        raise _MissionExit(intent)
                    runtime.activation_guard = None
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
        except _MissionExit as exit_request:
            if runtime.pending_terminal is None:
                runtime.pending_terminal = exit_request.intent
        except Exception as exc:
            try:
                self.fail(mission_id, str(exc), retryable=True)
            except _MissionExit:
                pass
        finally:
            # A mission may accidentally catch BaseException and swallow the
            # private unwind sentinel. Finalize the recorded request after all
            # user callback frames have left regardless.
            intent = runtime.pending_terminal
            if intent is not None:
                runtime.worker = None
                self._publish_intent_transition(intent)
                try:
                    self._finalize_pending_terminal(runtime, intent)
                except MissionCleanupError:
                    pass

    def _finalize_pending_terminal(
        self,
        runtime: MissionRuntime,
        intent: PendingTerminalIntent,
        *,
        retry_cleanup: bool = False,
    ) -> MissionSnapshot:
        self._join_worker(runtime)
        with runtime.terminal_lock:
            with self.engine._condition:
                if runtime.pending_terminal is not intent:
                    if (
                        runtime.pending_terminal is None
                        or runtime.snapshot.generation != intent.generation
                    ):
                        return runtime.snapshot
                    raise MissionTransitionError("Mission terminal intent changed")
                cleanup_error = runtime.cleanup_error
            if cleanup_error is not None and not retry_cleanup:
                raise MissionCleanupError(
                    f"Mission {runtime.mission.id} cleanup failed: {cleanup_error}"
                ) from cleanup_error
            self._cleanup_or_raise(runtime)
            if intent.phase is MissionPhase.SUCCEEDED:
                snapshot = self._complete_stopping(
                    runtime,
                    intent.result,
                    cleanup=False,
                    intent=intent,
                )
            elif intent.phase is MissionPhase.FAILED:
                snapshot = self._finish_failure(
                    runtime,
                    intent.reason,
                    intent.retryable,
                    cleanup=False,
                    intent=intent,
                )
            else:
                with self.engine._condition:
                    if runtime.pending_terminal is not intent:
                        raise MissionTransitionError("Mission terminal intent changed")
                    snapshot, transition = self._transition_locked(
                        runtime,
                        intent.phase,
                        reason=intent.reason,
                        requester_id=intent.requester_id,
                    )
                    runtime.pending_terminal = None
                self._publish_transition(transition)
                self.engine.scheduler._after_terminal(
                    runtime.mission.id,
                    succeeded=False,
                )
        return snapshot

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
        intent: PendingTerminalIntent | None = None
        snapshot = runtime.snapshot
        with self.engine._condition:
            self.engine._authorize_locked(requester_id, runtime)
            current = runtime.snapshot.phase
            if current is terminal:
                return runtime.snapshot
            if current.terminal:
                return runtime.snapshot
            if runtime.pending_terminal is not None:
                intent = runtime.pending_terminal
                if intent.phase is not terminal:
                    raise MissionTransitionError(
                        "Mission already has a different terminal intent"
                    )
            runtime.stop_event.set()
            if current in {MissionPhase.REGISTERED, MissionPhase.QUEUED}:
                snapshot, transition = self._transition_locked(
                    runtime,
                    terminal,
                    requester_id=requester_id,
                    reason=reason,
                )
            elif intent is None:
                _, transition = self._transition_locked(
                    runtime,
                    MissionPhase.STOPPING,
                    requester_id=requester_id,
                    reason=reason,
                )
                intent = self._set_terminal_intent_locked(
                    runtime,
                    terminal,
                    reason=reason,
                    requester_id=requester_id,
                    transition=transition,
                )
                transition = None
            if runtime.worker is threading.current_thread() and intent is not None:
                raise _MissionExit(intent)

        if intent is not None:
            self._publish_intent_transition(intent)
            return self._finalize_pending_terminal(runtime, intent)

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

    def _cleanup_or_raise(self, runtime: MissionRuntime) -> None:
        try:
            self._cleanup_runtime(runtime)
        except Exception as exc:
            runtime.cleanup_error = exc
            with self.engine._condition:
                runtime.snapshot = runtime.snapshot.evolve(
                    cleanup_pending=True,
                    cleanup_error=str(exc),
                )
                self.engine._condition.notify_all()
            self.engine._emit(
                MissionEventType.ERROR,
                f"Mission cleanup failed: {exc}",
                mission_id=runtime.mission.id,
            )
            raise MissionCleanupError(
                f"Mission {runtime.mission.id} cleanup failed: {exc}"
            ) from exc
        runtime.cleanup_error = None
        with self.engine._condition:
            runtime.snapshot = runtime.snapshot.evolve(
                cleanup_pending=False,
                cleanup_error=None,
            )
            self.engine._condition.notify_all()

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
            runtime.queued_monotonic = time.monotonic()
        if current is MissionPhase.STARTING:
            changes.update(
                generation=runtime.snapshot.generation + 1,
                attempt=runtime.snapshot.attempt + 1,
                started_at=now,
                finished_at=None,
                next_retry_at=None,
                progress=0.0,
                result={},
                queued_at=None,
            )
            runtime.active_elapsed = 0.0
            runtime.active_started_monotonic = None
            runtime.attempt_started_monotonic = time.monotonic()
            runtime.queued_monotonic = None
            runtime.next_retry_monotonic = None
        if current is MissionPhase.RUNNING:
            runtime.active_started_monotonic = time.monotonic()
        elif previous is MissionPhase.RUNNING:
            runtime.active_elapsed = self._active_elapsed_locked(runtime)
            runtime.active_started_monotonic = None
        if current.terminal:
            changes["finished_at"] = now
            runtime.attempt_started_monotonic = None
        if result is not None:
            changes["result"] = dict(result)
        if progress is not None:
            changes["progress"] = progress
        runtime.snapshot = runtime.snapshot.evolve(**changes)
        self.engine._update_phase_indexes_locked(runtime, previous, current)
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
        next_retry_monotonic: float | None = None,
    ) -> tuple[MissionSnapshot, MissionTransition | None]:
        if runtime.snapshot.phase is MissionPhase.QUEUED:
            if next_retry_at is not None:
                runtime.snapshot = runtime.snapshot.evolve(next_retry_at=next_retry_at)
                runtime.next_retry_monotonic = next_retry_monotonic
            return runtime.snapshot, None
        queue_limit = self.engine._max_queued_missions
        if queue_limit is not None and len(self.engine._queued_ids) >= queue_limit:
            raise MissionConflictError("Mission queue capacity reached")
        snapshot, transition = self._transition_locked(
            runtime,
            MissionPhase.QUEUED,
            reason=reason,
        )
        if next_retry_at is not None:
            runtime.snapshot = snapshot.evolve(next_retry_at=next_retry_at)
            runtime.next_retry_monotonic = next_retry_monotonic
            snapshot = runtime.snapshot
        self.engine._scheduler_wake.set()
        return snapshot, transition
