"""Mission lifecycle commands shared by the concrete engine."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable, Mapping
from typing import Any

from .base import Mission
from .enums import MissionEventType, MissionPhase, ensure_mission_transition
from .errors import MissionTimeoutError, MissionTransitionError
from .models import MissionSnapshot, MissionTransition
from .runtime import MissionRuntime


MissionReference = Mission | int


class MissionLifecycleMixin:
    def pause(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        runtime = self._runtime(mission)
        with self._condition:
            self._authorize_locked(requester_id, runtime)
            if runtime.snapshot.phase is MissionPhase.PAUSED:
                return runtime.snapshot
            self._transition_locked(
                runtime,
                MissionPhase.PAUSING,
                reason=reason,
                requester_id=requester_id,
            )
        try:
            runtime.mission.pause()
        except Exception as exc:
            return self.fail(runtime.mission.id, str(exc))
        with self._condition:
            return self._transition_locked(
                runtime,
                MissionPhase.PAUSED,
                reason=reason,
                requester_id=requester_id,
            )

    def resume(
        self,
        mission: MissionReference,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        runtime = self._runtime(mission)
        with self._condition:
            self._authorize_locked(requester_id, runtime)
            if runtime.snapshot.phase is MissionPhase.RUNNING:
                return runtime.snapshot
            if runtime.snapshot.phase is not MissionPhase.PAUSED:
                raise MissionTransitionError("Only a paused mission can resume")
        try:
            runtime.mission.resume()
        except Exception as exc:
            return self.fail(runtime.mission.id, str(exc))
        with self._condition:
            return self._transition_locked(
                runtime,
                MissionPhase.RUNNING,
                reason=reason,
                requester_id=requester_id,
            )

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
        runtime = self._runtime(mission)
        with self._condition:
            if runtime.snapshot.phase is MissionPhase.SUCCEEDED:
                return runtime.snapshot
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            runtime.stop_event.set()
        try:
            self._cleanup_runtime(runtime)
        except Exception as exc:
            return self.fail(runtime.mission.id, f"Mission cleanup failed: {exc}")
        with self._condition:
            if runtime.snapshot.phase is MissionPhase.STOPPING:
                return runtime.snapshot
            snapshot = self._transition_locked(
                runtime,
                MissionPhase.SUCCEEDED,
                result=dict(result or {}),
                progress=1.0,
                reason="Mission completed",
            )
        self._after_terminal(runtime.mission.id, succeeded=True)
        return snapshot

    def fail(
        self,
        mission: MissionReference,
        reason: str,
        *,
        retryable: bool = False,
    ) -> MissionSnapshot:
        runtime = self._runtime(mission)
        failure_reason = str(reason).strip() or "Mission failed"
        with self._condition:
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            runtime.stop_event.set()
        try:
            self._cleanup_runtime(runtime)
        except Exception as exc:
            failure_reason = f"{failure_reason}; cleanup failed: {exc}"
        with self._condition:
            if runtime.snapshot.phase.terminal:
                return runtime.snapshot
            snapshot = self._transition_locked(
                runtime,
                MissionPhase.FAILED,
                reason=failure_reason,
            )
            should_retry = (
                retryable and snapshot.attempt < runtime.mission.retry.attempts
            )
            if should_retry:
                snapshot = self._queue_locked(
                    runtime,
                    "Mission queued for retry",
                    next_retry_at=time.time() + runtime.mission.retry.delay,
                )
        if not should_retry:
            self._after_terminal(runtime.mission.id, succeeded=False)
        else:
            self._emit(
                MissionEventType.RETRY,
                "Mission retry scheduled",
                mission_id=runtime.mission.id,
                fields={"attempt": snapshot.attempt, "at": snapshot.next_retry_at},
            )
            self._scheduler_wake.set()
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
        with self._condition:
            runtime = self._runtime_locked(self._mission_id(mission))
            if not runtime.snapshot.phase.active:
                raise MissionTransitionError("Inactive mission progress cannot change")
            runtime.snapshot = runtime.snapshot.evolve(progress=value, reason=reason)
            snapshot = runtime.snapshot
            self._condition.notify_all()
        self._emit(
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
        with self._condition:
            runtime = self._runtime_locked(self._mission_id(mission))
            checkpoints = dict(runtime.snapshot.checkpoints)
            checkpoints[name] = dict(values or {})
            runtime.snapshot = runtime.snapshot.evolve(checkpoints=checkpoints)
            snapshot = runtime.snapshot
            self._condition.notify_all()
        self._emit(
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
        mission_id = self._mission_id(mission)
        with self._condition:
            self._runtime_locked(mission_id)
            ready = self._condition.wait_for(
                lambda: self._runtime_locked(mission_id).snapshot.phase.terminal,
                timeout=timeout,
            )
            return self._runtime_locked(mission_id).snapshot if ready else None

    def stop_matching(
        self,
        requester_id: int,
        *,
        tags: Iterable[str] = (),
        resources: Iterable[str] = (),
    ) -> tuple[MissionSnapshot, ...]:
        """Let one mission stop authorized active work without direct references."""

        targets = self._matching_active(requester_id, tags=tags, resources=resources)
        return tuple(
            self.stop_mission(
                mission_id,
                requester_id=requester_id,
                reason=f"Stopped by mission {requester_id}",
            )
            for mission_id in targets
        )

    def _run_mission(self, mission_id: int, generation: int) -> None:
        runtime = self._runtime(mission_id)
        started = time.monotonic()
        try:
            with self._condition:
                if (
                    runtime.snapshot.generation != generation
                    or runtime.snapshot.phase is not MissionPhase.STARTING
                ):
                    return
                self._transition_locked(runtime, MissionPhase.RUNNING)
            runtime.mission.start()
            while not runtime.stop_event.wait(runtime.mission.tick_interval):
                with self._condition:
                    snapshot = runtime.snapshot
                if snapshot.generation != generation or snapshot.phase.terminal:
                    break
                if snapshot.phase is MissionPhase.PAUSED:
                    continue
                elapsed = time.monotonic() - started
                timeout = runtime.mission.timeout_seconds
                if timeout is not None and elapsed >= timeout:
                    self.fail(mission_id, "Mission execution timed out", retryable=True)
                    break
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
        runtime = self._runtime(mission)
        with self._condition:
            self._authorize_locked(requester_id, runtime)
            current = runtime.snapshot.phase
            if current is terminal:
                return runtime.snapshot
            if current.terminal:
                return runtime.snapshot
            runtime.stop_event.set()
            if current is MissionPhase.QUEUED:
                snapshot = self._transition_locked(
                    runtime,
                    terminal,
                    requester_id=requester_id,
                    reason=reason,
                )
                worker = None
            elif current is MissionPhase.STOPPING:
                snapshot = runtime.snapshot
                worker = runtime.worker
            else:
                self._transition_locked(
                    runtime,
                    MissionPhase.STOPPING,
                    requester_id=requester_id,
                    reason=reason,
                )
                worker = runtime.worker

        if current is not MissionPhase.QUEUED:
            try:
                self._cleanup_runtime(runtime)
            except Exception as exc:
                return self.fail(runtime.mission.id, str(exc))
            if worker is not None and worker is not threading.current_thread():
                worker.join(self._stop_timeout)
                if worker.is_alive():
                    raise MissionTimeoutError(
                        f"Mission {runtime.mission.id} did not stop in time"
                    )
            with self._condition:
                if runtime.snapshot.phase is MissionPhase.STOPPING:
                    snapshot = self._transition_locked(
                        runtime,
                        terminal,
                        requester_id=requester_id,
                        reason=reason,
                    )
                else:
                    snapshot = runtime.snapshot
        self._after_terminal(runtime.mission.id, succeeded=False)
        self._scheduler_wake.set()
        return snapshot

    @staticmethod
    def _cleanup_runtime(runtime: MissionRuntime) -> None:
        with runtime.cleanup_lock:
            if runtime.cleaned:
                return
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
    ) -> MissionSnapshot:
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
        self._condition.notify_all()
        self.transitions.publish(transition)
        self._emit(
            MissionEventType.TRANSITION,
            f"Mission {previous.value} -> {current.value}",
            mission_id=runtime.mission.id,
            requester_id=requester_id,
            generation=runtime.snapshot.generation,
            fields={"previous": previous.value, "current": current.value},
        )
        return runtime.snapshot

    def _queue_locked(
        self,
        runtime: MissionRuntime,
        reason: str,
        *,
        next_retry_at: float | None = None,
    ) -> MissionSnapshot:
        if runtime.snapshot.phase is MissionPhase.QUEUED:
            if next_retry_at is not None:
                runtime.snapshot = runtime.snapshot.evolve(next_retry_at=next_retry_at)
            return runtime.snapshot
        snapshot = self._transition_locked(
            runtime,
            MissionPhase.QUEUED,
            reason=reason,
        )
        if next_retry_at is not None:
            runtime.snapshot = snapshot.evolve(next_retry_at=next_retry_at)
            snapshot = runtime.snapshot
        self._scheduler_wake.set()
        return snapshot
