from __future__ import annotations

import threading
import time
import unittest

from src.core.mission import (
    Mission,
    MissionChain,
    MissionConflictPolicy,
    MissionEngine,
    MissionPermissionError,
    MissionPhase,
    MissionPrerequisitePolicy,
    MissionPriority,
    MissionRetryPolicy,
    MissionTimeoutError,
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
