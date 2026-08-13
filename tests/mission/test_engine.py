from __future__ import annotations

import threading
import time
import unittest

from src.core.mission import (
    Mission,
    MissionChain,
    MissionConflictPolicy,
    MissionEngine,
    MissionLifecycle,
    MissionPermissionError,
    MissionPhase,
    MissionPrerequisitePolicy,
    MissionPriority,
    MissionRetryPolicy,
    MissionScheduler,
    MissionSnapshot,
    MissionTimeoutError,
    MissionTransitionError,
)


def wait_for_phase(
    engine: MissionEngine,
    mission: Mission,
    phase: MissionPhase,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine.snapshot(mission).phase is phase:
            return
        time.sleep(0.001)
    raise AssertionError(
        f"Mission did not reach {phase}: {engine.snapshot(mission).phase}"
    )


class CompletingMission(Mission):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.stop_count = 0

    def start(self) -> None:
        self.checkpoint("started", ready=True)
        self.update_progress(0.5)
        self.complete({"ok": True})

    def stop(self) -> None:
        self.stop_count += 1


class BlockingMission(Mission):
    tick_interval = 0.002

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.ticks = 0

    def start(self) -> None:
        self.started.set()

    def tick(self, elapsed_seconds: float) -> None:
        self.ticks += 1

    def stop(self) -> None:
        self.stopped.set()


class ExclusiveMission(BlockingMission):
    resources = frozenset({"flight-control"})
    conflict_policy = MissionConflictPolicy.QUEUE


class RejectingExclusiveMission(BlockingMission):
    resources = frozenset({"flight-control"})


class CriticalMission(BlockingMission):
    priority = int(MissionPriority.CRITICAL)
    resources = frozenset({"flight-control"})
    conflict_policy = MissionConflictPolicy.PREEMPT_LOWER


class LowPriorityMission(BlockingMission):
    priority = int(MissionPriority.LOW)
    tags = frozenset({"background"})


class CriticalCoordinator(BlockingMission):
    priority = int(MissionPriority.CRITICAL)


class DependentMission(CompletingMission):
    prerequisites = frozenset({CompletingMission})
    prerequisite_policy = MissionPrerequisitePolicy.QUEUE


class TimedMission(BlockingMission):
    timeout_seconds = 0.01


class QueueTimedMission(ExclusiveMission):
    queue_timeout_seconds = 0.01


class FlakyMission(Mission):
    retry = MissionRetryPolicy(attempts=2, delay=0.001)

    def __init__(self) -> None:
        super().__init__()
        self.starts = 0

    def start(self) -> None:
        self.starts += 1
        if self.starts == 1:
            raise RuntimeError("temporary failure")
        self.complete({"attempt": self.starts})

    def stop(self) -> None:
        pass


class StuckMission(Mission):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def start(self) -> None:
        self.entered.set()
        self.release.wait()

    def stop(self) -> None:
        pass


class BlockingTickMission(Mission):
    tick_interval = 0.001

    def __init__(self) -> None:
        super().__init__()
        self.tick_entered = threading.Event()
        self.release_tick = threading.Event()
        self.stop_entered = threading.Event()

    def start(self) -> None:
        pass

    def tick(self, elapsed_seconds: float) -> None:
        self.tick_entered.set()
        self.release_tick.wait()

    def stop(self) -> None:
        self.stop_entered.set()


class PausableTickMission(BlockingTickMission):
    def __init__(self) -> None:
        super().__init__()
        self.pause_entered = threading.Event()

    def pause(self) -> None:
        self.pause_entered.set()


class PausedTimeoutMission(BlockingMission):
    tick_interval = 0.001
    timeout_seconds = 0.1


class RecordingLifecycle(MissionLifecycle):
    def __init__(self) -> None:
        super().__init__()
        self.progress_values: list[float] = []

    def progress(
        self,
        mission: Mission | int,
        value: float,
        *,
        reason: str = "",
    ) -> MissionSnapshot:
        self.progress_values.append(value)
        return super().progress(mission, value, reason=reason)


class RecordingScheduler(MissionScheduler):
    def __init__(self) -> None:
        super().__init__()
        self.launched: list[int] = []

    def launch(
        self,
        mission: Mission | int,
        *,
        requester_id: int | None = None,
        reason: str = "",
    ) -> MissionSnapshot:
        mission_id = mission.id if isinstance(mission, Mission) else mission
        self.launched.append(mission_id)
        return super().launch(
            mission,
            requester_id=requester_id,
            reason=reason,
        )


class MissionComponentTests(unittest.TestCase):
    def test_engine_uses_ready_components_without_mixin_inheritance(self) -> None:
        lifecycle = RecordingLifecycle()
        scheduler = RecordingScheduler()
        engine = MissionEngine(
            lifecycle=lifecycle,
            scheduler=scheduler,
            scheduler_interval=0.001,
        )
        mission = CompletingMission()
        try:
            self.assertNotIsInstance(engine, MissionLifecycle)
            self.assertNotIsInstance(engine, MissionScheduler)
            self.assertIs(engine.lifecycle, lifecycle)
            self.assertIs(engine.scheduler, scheduler)
            self.assertIs(lifecycle.engine, engine)
            self.assertIs(scheduler.engine, engine)

            engine.launch(mission)
            result = engine.wait(mission, timeout=1.0)

            self.assertEqual(result.phase, MissionPhase.SUCCEEDED)
            self.assertEqual(scheduler.launched, [mission.id])
            self.assertEqual(lifecycle.progress_values, [0.5])
        finally:
            engine.close()

    def test_components_require_one_explicit_engine_owner(self) -> None:
        lifecycle = MissionLifecycle()
        scheduler = MissionScheduler()
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            _ = lifecycle.engine
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            _ = scheduler.engine

        first = MissionEngine(lifecycle=lifecycle, scheduler=scheduler)
        second = MissionEngine()
        try:
            with self.assertRaisesRegex(RuntimeError, "another engine"):
                lifecycle.bind(second)
            with self.assertRaisesRegex(RuntimeError, "another engine"):
                scheduler.bind(second)
        finally:
            first.close()
            second.close()


class MissionEngineLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MissionEngine(scheduler_interval=0.001, stop_timeout=0.5)

    def tearDown(self) -> None:
        self.engine.close()

    def test_launch_binds_control_tracks_progress_and_completes(self) -> None:
        mission = CompletingMission()

        self.engine.launch(mission)
        snapshot = self.engine.wait(mission, timeout=1.0)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.phase, MissionPhase.SUCCEEDED)
        self.assertEqual(snapshot.progress, 1.0)
        self.assertEqual(snapshot.result, {"ok": True})
        self.assertEqual(snapshot.checkpoints["started"], {"ready": True})
        self.assertEqual(mission.stop_count, 1)
        self.assertGreaterEqual(len(self.engine.query_events()), 4)

    def test_concurrent_launch_is_idempotent_for_one_mission(self) -> None:
        mission = BlockingMission()
        callers = 8
        barrier = threading.Barrier(callers)
        results: list[MissionSnapshot] = []
        errors: list[BaseException] = []

        def launch() -> None:
            try:
                barrier.wait()
                results.append(self.engine.launch(mission))
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=launch) for _ in range(callers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1.0)

        self.assertFalse(errors)
        self.assertEqual(len(results), callers)
        self.assertTrue(mission.started.wait(1.0))
        self.assertEqual(len(self.engine.snapshots()), 1)
        self.assertEqual(self.engine.snapshot(mission).generation, 1)

    def test_complete_rejects_non_running_phases_without_side_effects(self) -> None:
        phases = (
            MissionPhase.STARTING,
            MissionPhase.PAUSING,
            MissionPhase.PAUSED,
            MissionPhase.STOPPING,
        )
        for phase in phases:
            with self.subTest(phase=phase):
                mission = BlockingMission(name=f"Complete guard {phase.value}")
                self.engine.register(mission)
                runtime = self.engine._runtime(mission)
                with self.engine._condition:
                    runtime.snapshot = runtime.snapshot.evolve(phase=phase)

                with self.assertRaisesRegex(
                    MissionTransitionError,
                    "running mission",
                ):
                    self.engine.complete(mission)

                self.assertFalse(runtime.stop_event.is_set())
                self.assertFalse(runtime.cleaned)
                self.assertEqual(runtime.snapshot.phase, phase)
                with self.engine._condition:
                    runtime.snapshot = runtime.snapshot.evolve(
                        phase=MissionPhase.STOPPED
                    )

    def test_queue_timeout_uses_monotonic_age_and_launch_clears_marker(self) -> None:
        owner = ExclusiveMission()
        waiting = QueueTimedMission()
        self.engine.launch(owner)
        self.assertTrue(owner.started.wait(1.0))
        self.assertEqual(self.engine.launch(waiting).phase, MissionPhase.QUEUED)
        runtime = self.engine._runtime(waiting)

        with self.engine._condition:
            runtime.snapshot = runtime.snapshot.evolve(queued_at=0.0)
        self.engine.scheduler._promote_queued()
        self.assertEqual(self.engine.snapshot(waiting).phase, MissionPhase.QUEUED)

        self.engine.stop_mission(owner)
        self.assertTrue(waiting.started.wait(1.0))
        self.assertIsNone(runtime.queued_monotonic)
        self.assertIsNone(self.engine.snapshot(waiting).queued_at)

    def test_non_conflicting_missions_run_in_parallel_and_pause_resume(self) -> None:
        first = BlockingMission(name="First")
        second = BlockingMission(name="Second")

        self.engine.run_parallel(first, second)
        self.assertTrue(first.started.wait(1.0))
        self.assertTrue(second.started.wait(1.0))
        self.assertEqual(
            set(self.engine.manager_snapshot().active_missions),
            {first.id, second.id},
        )

        self.engine.pause(first)
        self.assertEqual(self.engine.snapshot(first).phase, MissionPhase.PAUSED)
        self.engine.resume(first)
        self.assertEqual(self.engine.snapshot(first).phase, MissionPhase.RUNNING)

        self.engine.stop_mission(first)
        self.engine.stop_mission(second)
        self.assertTrue(first.stopped.is_set())
        self.assertTrue(second.stopped.is_set())

    def test_resource_conflict_queues_then_releases_mission(self) -> None:
        first = ExclusiveMission(name="Owner")
        second = ExclusiveMission(name="Waiting")

        self.engine.launch(first)
        self.assertTrue(first.started.wait(1.0))
        queued = self.engine.launch(second)
        self.assertEqual(queued.phase, MissionPhase.QUEUED)

        self.engine.stop_mission(first)
        self.assertTrue(second.started.wait(1.0))
        wait_for_phase(self.engine, second, MissionPhase.RUNNING)

    def test_higher_priority_preempts_and_lower_priority_is_denied(self) -> None:
        low = ExclusiveMission(name="Low resource owner")
        critical = CriticalMission(name="Critical")

        self.engine.launch(low)
        self.assertTrue(low.started.wait(1.0))
        self.engine.launch(critical)
        self.assertTrue(critical.started.wait(1.0))
        self.assertEqual(self.engine.snapshot(low).phase, MissionPhase.STOPPED)

        weak = LowPriorityMission()
        self.engine.launch(weak)
        self.assertTrue(weak.started.wait(1.0))
        with self.assertRaises(MissionPermissionError):
            self.engine.stop_mission(critical, requester_id=weak.id)

    def test_retry_policy_relaunches_failed_work(self) -> None:
        mission = FlakyMission()

        self.engine.launch(mission)
        snapshot = self.engine.wait(mission, timeout=1.0)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.phase, MissionPhase.SUCCEEDED)
        self.assertEqual(snapshot.attempt, 2)
        self.assertEqual(mission.starts, 2)

    def test_prerequisite_queue_and_tag_based_mission_control(self) -> None:
        dependent = DependentMission()
        queued = self.engine.launch(dependent)
        self.assertEqual(queued.phase, MissionPhase.QUEUED)

        prerequisite = CompletingMission()
        self.engine.launch(prerequisite)
        self.assertEqual(self.engine.wait(prerequisite, 1.0).phase, MissionPhase.SUCCEEDED)
        self.assertEqual(self.engine.wait(dependent, 1.0).phase, MissionPhase.SUCCEEDED)

        coordinator = CriticalCoordinator()
        background = LowPriorityMission()
        self.engine.run_parallel(coordinator, background)
        self.assertTrue(coordinator.started.wait(1.0))
        self.assertTrue(background.started.wait(1.0))

        stopped = coordinator.stop_missions(tags={"background"})
        self.assertEqual(tuple(item.mission_id for item in stopped), (background.id,))
        self.assertEqual(self.engine.snapshot(background).phase, MissionPhase.STOPPED)

    def test_stuck_worker_is_retained_until_shutdown_can_be_retried(self) -> None:
        engine = MissionEngine(scheduler_interval=0.001, stop_timeout=0.01)
        mission = StuckMission()
        try:
            engine.launch(mission)
            self.assertTrue(mission.entered.wait(1.0))

            with self.assertRaises(MissionTimeoutError):
                engine.stop_mission(mission)
            self.assertEqual(engine.snapshot(mission).phase, MissionPhase.STOPPING)

            mission.release.set()
            snapshot = engine.stop_mission(mission)
            self.assertEqual(snapshot.phase, MissionPhase.STOPPED)
        finally:
            mission.release.set()
            engine.close()

    def test_execution_and_queue_timeouts_fail_deterministically(self) -> None:
        timed = TimedMission()
        self.engine.launch(timed)
        timed_result = self.engine.wait(timed, timeout=1.0)
        self.assertEqual(timed_result.phase, MissionPhase.FAILED)
        self.assertIn("timed out", timed_result.reason)

        owner = ExclusiveMission()
        waiting = QueueTimedMission()
        self.engine.launch(owner)
        self.assertTrue(owner.started.wait(1.0))
        self.assertEqual(self.engine.launch(waiting).phase, MissionPhase.QUEUED)
        waiting_result = self.engine.wait(waiting, timeout=1.0)
        self.assertEqual(waiting_result.phase, MissionPhase.FAILED)
        self.assertIn("queue timed out", waiting_result.reason)

    def test_stop_waits_for_tick_before_cleanup(self) -> None:
        mission = BlockingTickMission()
        self.engine.launch(mission)
        self.assertTrue(mission.tick_entered.wait(1.0))

        stopped: list[MissionSnapshot] = []
        stopper = threading.Thread(
            target=lambda: stopped.append(self.engine.stop_mission(mission))
        )
        stopper.start()
        time.sleep(0.02)

        self.assertFalse(mission.stop_entered.is_set())
        mission.release_tick.set()
        stopper.join(1.0)
        self.assertFalse(stopper.is_alive())
        self.assertTrue(mission.stop_entered.is_set())
        self.assertEqual(stopped[0].phase, MissionPhase.STOPPED)

    def test_pause_waits_for_tick_and_blocks_new_ticks(self) -> None:
        mission = PausableTickMission()
        self.engine.launch(mission)
        self.assertTrue(mission.tick_entered.wait(1.0))

        paused: list[MissionSnapshot] = []
        pauser = threading.Thread(target=lambda: paused.append(self.engine.pause(mission)))
        pauser.start()
        time.sleep(0.02)

        self.assertFalse(mission.pause_entered.is_set())
        mission.release_tick.set()
        pauser.join(1.0)
        self.assertEqual(paused[0].phase, MissionPhase.PAUSED)
        self.assertTrue(mission.pause_entered.is_set())

    def test_transition_callback_can_stop_starting_mission_safely(self) -> None:
        mission = BlockingMission()

        def stop_on_starting(transition: object) -> None:
            if getattr(transition, "current", None) is MissionPhase.STARTING:
                self.engine.stop_mission(mission)

        self.engine.transitions.subscribe(stop_on_starting)
        snapshot = self.engine.launch(mission)

        self.assertEqual(snapshot.phase, MissionPhase.STOPPED)
        self.assertFalse(mission.started.is_set())

    def test_execution_timeout_excludes_paused_time(self) -> None:
        mission = PausedTimeoutMission()
        self.engine.launch(mission)
        self.assertTrue(mission.started.wait(1.0))
        time.sleep(0.01)
        self.engine.pause(mission)
        time.sleep(0.15)

        self.assertEqual(self.engine.snapshot(mission).phase, MissionPhase.PAUSED)
        self.engine.resume(mission)
        time.sleep(0.01)
        self.assertEqual(self.engine.snapshot(mission).phase, MissionPhase.RUNNING)


class MissionEngineChainTests(unittest.TestCase):
    def test_chain_runs_each_mission_in_order(self) -> None:
        engine = MissionEngine(scheduler_interval=0.001)
        try:
            chain = MissionChain(
                "startup",
                (CompletingMission, CompletingMission),
            )
            engine.start_chain(chain)

            deadline = time.monotonic() + 1.0
            while engine.chain_snapshot("startup").active and time.monotonic() < deadline:
                time.sleep(0.001)

            snapshot = engine.chain_snapshot("startup")
            self.assertTrue(snapshot.completed)
            self.assertFalse(snapshot.failed)
            self.assertEqual(
                len(
                    [
                        item
                        for item in engine.snapshots()
                        if item.phase is MissionPhase.SUCCEEDED
                    ]
                ),
                2,
            )
        finally:
            engine.close()

    def test_chain_factory_failure_marks_chain_inactive(self) -> None:
        def broken_factory(_mission_type: type[Mission]) -> Mission:
            raise RuntimeError("factory failed")

        engine = MissionEngine(mission_factory=broken_factory)
        try:
            with self.assertRaisesRegex(RuntimeError, "factory failed"):
                engine.start_chain(MissionChain("broken", (CompletingMission,)))

            snapshot = engine.chain_snapshot("broken")
            self.assertFalse(snapshot.active)
            self.assertTrue(snapshot.failed)
            self.assertIn("factory failed", snapshot.reason)
        finally:
            engine.close()

    def test_chain_launch_conflict_marks_chain_inactive(self) -> None:
        engine = MissionEngine(scheduler_interval=0.001)
        owner = ExclusiveMission()
        try:
            engine.launch(owner)
            self.assertTrue(owner.started.wait(1.0))
            engine.start_chain(
                MissionChain(
                    "conflicted",
                    (CompletingMission, RejectingExclusiveMission),
                )
            )

            deadline = time.monotonic() + 1.0
            while engine.chain_snapshot("conflicted").active:
                if time.monotonic() >= deadline:
                    self.fail("Mission chain remained active after launch conflict")
                time.sleep(0.001)

            snapshot = engine.chain_snapshot("conflicted")
            self.assertTrue(snapshot.failed)
            self.assertIn("conflicts", snapshot.reason)
        finally:
            engine.close()
