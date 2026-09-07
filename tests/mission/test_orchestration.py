from __future__ import annotations

import threading
import time
import unittest

from src.core.compatibility import ExceptionGroup
from src.core.mission import (
    BackgroundFailurePolicy,
    Mission,
    MissionChain,
    MissionConflictError,
    MissionEngine,
    MissionEventType,
    MissionNode,
    MissionNotFoundError,
    MissionParallelGroup,
    MissionParallelStage,
    MissionPhase,
    MissionRetryPolicy,
    MissionScheduler,
    OwnerTerminationPolicy,
    ParallelFailurePolicy,
)


def wait_until(predicate: object, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return
        time.sleep(0.001)
    raise AssertionError("Condition was not satisfied before the timeout")


class IdleMission(Mission):
    tick_interval = 0.002

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self) -> None:
        self.started.set()

    def stop(self) -> None:
        self.stopped.set()


class ProducerMission(Mission):
    contexts: list[object] = []

    def start(self) -> None:
        type(self).contexts.append(self.runtime.chain_context)
        value = self.runtime.chain_context.input["value"]  # type: ignore[union-attr]
        self.complete({"value": value})

    def stop(self) -> None:
        pass


class ConsumerMission(Mission):
    contexts: list[object] = []

    def start(self) -> None:
        context = self.runtime.chain_context
        type(self).contexts.append(context)
        self.complete({"received": context.previous_result["value"]})  # type: ignore[union-attr]

    def stop(self) -> None:
        pass


class FailingMission(Mission):
    def start(self) -> None:
        self.fail("expected failure")

    def stop(self) -> None:
        pass


class TimedOutMission(IdleMission):
    timeout_seconds = 0.01


class NeverStartedMission(Mission):
    started = threading.Event()

    def start(self) -> None:
        type(self).started.set()
        self.complete()

    def stop(self) -> None:
        pass


class ContextAfterFailureMission(Mission):
    seen_phase: MissionPhase | None = None

    def start(self) -> None:
        context = self.runtime.chain_context
        type(self).seen_phase = context.previous_mission.phase  # type: ignore[union-attr]
        self.complete({"continued": True})

    def stop(self) -> None:
        pass


class RetryingMission(Mission):
    retry = MissionRetryPolicy(attempts=2)
    execution_ids: list[str] = []

    def __init__(self) -> None:
        super().__init__()
        self.starts = 0

    def start(self) -> None:
        self.starts += 1
        context = self.runtime.chain_context
        type(self).execution_ids.append(context.execution_id)  # type: ignore[union-attr]
        if self.starts == 1:
            raise RuntimeError("retry once")
        self.complete({"attempt": self.starts})

    def stop(self) -> None:
        pass


class ParallelA(Mission):
    a_started = threading.Event()
    b_started = threading.Event()

    def start(self) -> None:
        type(self).a_started.set()
        if not type(self).b_started.wait(1.0):
            self.fail("parallel sibling did not start")
            return
        self.complete({"a": 1})

    def stop(self) -> None:
        pass


class ParallelB(Mission):
    def start(self) -> None:
        ParallelA.b_started.set()
        if not ParallelA.a_started.wait(1.0):
            self.fail("parallel sibling did not start")
            return
        self.complete({"b": 2})

    def stop(self) -> None:
        pass


class ParallelConsumer(Mission):
    received: object = None

    def start(self) -> None:
        context = self.runtime.chain_context
        type(self).received = context.previous_result  # type: ignore[union-attr]
        self.complete({"done": True})

    def stop(self) -> None:
        pass


class ExclusiveA(IdleMission):
    resources = frozenset({"shared"})


class ExclusiveB(IdleMission):
    resources = frozenset({"shared"})


class MissionOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        ProducerMission.contexts.clear()
        ConsumerMission.contexts.clear()
        RetryingMission.execution_ids.clear()
        ContextAfterFailureMission.seen_phase = None
        ParallelA.a_started.clear()
        ParallelA.b_started.clear()
        ParallelConsumer.received = None
        NeverStartedMission.started.clear()

    def test_chain_transfers_input_results_and_immutable_context(self) -> None:
        with MissionEngine(scheduler_interval=0.001) as engine:
            snapshot = engine.start_chain(
                MissionChain("transfer", (ProducerMission, ConsumerMission)),
                input={"value": 7},
                metadata={"source": "test"},
            )
            wait_until(lambda: not engine.chain_snapshot(snapshot.execution_id).active)
            finished = engine.chain_snapshot(snapshot.execution_id)

        self.assertTrue(finished.completed)
        self.assertEqual(finished.context.results["ProducerMission"]["value"], 7)
        self.assertEqual(finished.context.results["ConsumerMission"]["received"], 7)
        with self.assertRaises(TypeError):
            finished.context.input["value"] = 8  # type: ignore[index]

    def test_chain_runs_are_isolated_and_repeated_nodes_are_unique(self) -> None:
        with MissionEngine(scheduler_interval=0.001) as engine:
            first = engine.start_chain(
                MissionChain("repeat", (ProducerMission, ProducerMission)),
                input={"value": 1},
            )
            second = engine.start_chain(
                MissionChain("repeat", (ProducerMission, ProducerMission)),
                input={"value": 2},
            )
            wait_until(lambda: not engine.chain_snapshot(first.execution_id).active)
            wait_until(lambda: not engine.chain_snapshot(second.execution_id).active)
            first = engine.chain_snapshot(first.execution_id)
            second = engine.chain_snapshot(second.execution_id)

        self.assertNotEqual(first.execution_id, second.execution_id)
        self.assertEqual(set(first.context.results), {"ProducerMission", "ProducerMission#2"})
        self.assertEqual(first.context.input["value"], 1)
        self.assertEqual(second.context.input["value"], 2)

    def test_failure_can_continue_with_terminal_context(self) -> None:
        with MissionEngine(scheduler_interval=0.001) as engine:
            run = engine.start_chain(
                MissionChain(
                    "continue",
                    (FailingMission, ContextAfterFailureMission),
                    stop_on_failure=False,
                )
            )
            wait_until(lambda: not engine.chain_snapshot(run.execution_id).active)
            finished = engine.chain_snapshot(run.execution_id)

        self.assertTrue(finished.completed)
        self.assertTrue(finished.failed)
        self.assertIs(ContextAfterFailureMission.seen_phase, MissionPhase.FAILED)

    def test_retry_preserves_execution_context(self) -> None:
        with MissionEngine(scheduler_interval=0.001) as engine:
            run = engine.start_chain(MissionChain("retry", (RetryingMission,)))
            wait_until(lambda: not engine.chain_snapshot(run.execution_id).active)

        self.assertEqual(RetryingMission.execution_ids, [run.execution_id] * 2)

    def test_timeout_and_cancel_end_a_chain_without_advancing(self) -> None:
        with MissionEngine(scheduler_interval=0.001) as engine:
            timed = engine.start_chain(
                MissionChain("timeout", (TimedOutMission, NeverStartedMission))
            )
            wait_until(lambda: not engine.chain_snapshot(timed.execution_id).active)
            self.assertTrue(engine.chain_snapshot(timed.execution_id).failed)
            self.assertFalse(NeverStartedMission.started.is_set())

            cancelled = engine.start_chain(
                MissionChain("cancel", (IdleMission, NeverStartedMission))
            )
            engine.cancel_chain(cancelled.execution_id)
            self.assertTrue(engine.chain_snapshot(cancelled.execution_id).cancelled)
            self.assertFalse(NeverStartedMission.started.is_set())

    def test_parallel_group_runs_concurrently_and_collects_results(self) -> None:
        group = MissionParallelGroup(
            "parallel",
            (ParallelA, ParallelB),
        )
        with MissionEngine(scheduler_interval=0.001) as engine:
            run = engine.start_parallel(group)
            wait_until(lambda: not engine.parallel_snapshot(run.execution_id).active)
            finished = engine.parallel_snapshot(run.execution_id)

        self.assertTrue(finished.completed)
        self.assertEqual(finished.results["ParallelA"]["a"], 1)
        self.assertEqual(finished.results["ParallelB"]["b"], 2)

        with self.assertRaisesRegex(ValueError, "unique"):
            MissionParallelGroup("duplicate", (ParallelA, ParallelA))

    def test_parallel_failure_cancels_remaining_children(self) -> None:
        blocker = IdleMission()

        def factory(mission_type: type[Mission]) -> Mission:
            return blocker if mission_type is IdleMission else mission_type()

        group = MissionParallelGroup(
            "cancel-siblings",
            (MissionNode("blocker", IdleMission), MissionNode("failure", FailingMission)),
            ParallelFailurePolicy.CANCEL_REMAINING,
        )
        with MissionEngine(mission_factory=factory, scheduler_interval=0.001) as engine:
            run = engine.start_parallel(group)
            wait_until(lambda: not engine.parallel_snapshot(run.execution_id).active)
            finished = engine.parallel_snapshot(run.execution_id)

        self.assertIs(finished.phases["blocker"], MissionPhase.CANCELLED)
        self.assertTrue(finished.failed)

    def test_early_parallel_failure_cancels_registered_sibling(self) -> None:
        class OrderedScheduler(MissionScheduler):
            def launch(self, mission: object, **options: object):
                snapshot = super().launch(mission, **options)  # type: ignore[arg-type]
                if isinstance(mission, FailingMission):
                    self.engine._runtime(mission).worker.join(1.0)
                return snapshot

        with MissionEngine(
            scheduler=OrderedScheduler(),
            scheduler_interval=0.001,
        ) as engine:
            run = engine.start_parallel(
                MissionParallelGroup(
                    "early-failure",
                    (FailingMission, NeverStartedMission),
                    ParallelFailurePolicy.CANCEL_REMAINING,
                )
            )
            finished = engine.wait_parallel(run.execution_id, 1.0)

        self.assertIsNotNone(finished)
        self.assertIs(
            finished.phases["NeverStartedMission"],  # type: ignore[union-attr]
            MissionPhase.CANCELLED,
        )
        self.assertFalse(NeverStartedMission.started.is_set())

    def test_wait_all_keeps_siblings_running_until_each_is_terminal(self) -> None:
        blocker = IdleMission()

        def factory(mission_type: type[Mission]) -> Mission:
            return blocker if mission_type is IdleMission else mission_type()

        group = MissionParallelGroup(
            "wait-all",
            (MissionNode("blocker", IdleMission), MissionNode("failure", FailingMission)),
            ParallelFailurePolicy.WAIT_ALL,
        )
        with MissionEngine(mission_factory=factory, scheduler_interval=0.001) as engine:
            run = engine.start_parallel(group)
            wait_until(lambda: engine.snapshot(blocker).phase is MissionPhase.RUNNING)
            self.assertTrue(engine.parallel_snapshot(run.execution_id).active)
            engine.complete(blocker, {"finished": True})
            wait_until(lambda: not engine.parallel_snapshot(run.execution_id).active)
            finished = engine.parallel_snapshot(run.execution_id)

        self.assertTrue(finished.failed)
        self.assertIs(finished.phases["blocker"], MissionPhase.SUCCEEDED)

    def test_parallel_group_stop_propagates_and_conflicts_are_rejected(self) -> None:
        with MissionEngine(scheduler_interval=0.001) as engine:
            with self.assertRaises(MissionConflictError):
                engine.start_parallel(
                    MissionParallelGroup(
                        "conflict",
                        (MissionNode("a", ExclusiveA), MissionNode("b", ExclusiveB)),
                    )
                )

            run = engine.start_parallel(
                MissionParallelGroup(
                    "stoppable",
                    (MissionNode("a", IdleMission), MissionNode("b", IdleMission)),
                )
            )
            engine.stop_parallel(run.execution_id)
            finished = engine.parallel_snapshot(run.execution_id)

        self.assertTrue(finished.stopped)
        self.assertTrue(all(phase is MissionPhase.STOPPED for phase in finished.phases.values()))

    def test_parallel_stop_attempts_every_child_and_can_be_retried(self) -> None:
        class StuckMission(IdleMission):
            def __init__(self) -> None:
                super().__init__()
                self.release = threading.Event()

            def start(self) -> None:
                self.started.set()
                self.release.wait()

        stuck = StuckMission()
        sibling = IdleMission()

        def factory(mission_type: type[Mission]) -> Mission:
            return stuck if mission_type is StuckMission else sibling

        engine = MissionEngine(
            mission_factory=factory,
            scheduler_interval=0.001,
            stop_timeout=0.01,
        )
        try:
            run = engine.start_parallel(
                MissionParallelGroup("retry-stop", (StuckMission, IdleMission))
            )
            self.assertTrue(stuck.started.wait(1.0))
            self.assertTrue(sibling.started.wait(1.0))

            with self.assertRaises(ExceptionGroup):
                engine.stop_parallel(run.execution_id)
            self.assertIs(engine.snapshot(sibling).phase, MissionPhase.STOPPED)
            self.assertTrue(engine.parallel_snapshot(run.execution_id).active)

            stuck.release.set()
            finished = engine.stop_parallel(run.execution_id)
            self.assertTrue(finished.stopped)
        finally:
            stuck.release.set()
            engine.close()

    def test_parallel_snapshot_is_live_and_execution_history_is_bounded(self) -> None:
        with MissionEngine(
            scheduler_interval=0.001,
            execution_history=2,
        ) as engine:
            group = MissionParallelGroup(
                "live",
                (MissionNode("left", IdleMission), MissionNode("right", IdleMission)),
            )
            run = engine.start_parallel(group)
            wait_until(
                lambda: all(
                    engine.snapshot(mission_id).phase is MissionPhase.RUNNING
                    for mission_id in run.children.values()
                )
            )
            self.assertTrue(
                all(
                    phase is MissionPhase.RUNNING
                    for phase in engine.parallel_snapshot(run.execution_id).phases.values()
                )
            )
            for mission_id in run.children.values():
                engine.complete(mission_id)
            self.assertIsNotNone(engine.wait_parallel(run.execution_id, 1.0))
            parallel_children = tuple(run.children.values())
            self.assertTrue(engine.forget_parallel(run.execution_id))
            self.assertTrue(
                set(parallel_children).isdisjoint(
                    engine.manager_snapshot().registered_missions
                )
            )

            chain_runs = []
            for index in range(3):
                chain_run = engine.start_chain(
                    MissionChain(f"bounded-{index}", (ProducerMission,)),
                    input={"value": index},
                )
                self.assertIsNotNone(engine.wait_chain(chain_run.execution_id, 1.0))
                chain_runs.append(chain_run)
            with self.assertRaises(MissionNotFoundError):
                engine.chain_snapshot(chain_runs[0].execution_id)
            self.assertNotIn(
                chain_runs[0].child_mission_ids[0],
                engine.manager_snapshot().registered_missions,
            )
            second_child = chain_runs[1].child_mission_ids[0]
            self.assertTrue(engine.forget_chain(chain_runs[1].execution_id))
            self.assertNotIn(
                second_child,
                engine.manager_snapshot().registered_missions,
            )
            self.assertFalse(engine.forget_chain(chain_runs[1].execution_id))

    def test_parallel_launch_failure_keeps_failed_group_snapshot(self) -> None:
        owner = ExclusiveA()
        with MissionEngine(scheduler_interval=0.001) as engine:
            engine.launch(owner)
            owner.started.wait(1.0)
            with self.assertRaises(MissionConflictError):
                engine.start_parallel(
                    MissionParallelGroup("blocked-group", (ExclusiveB,))
                )
            finished = engine.parallel_snapshot("blocked-group")

        self.assertFalse(finished.active)
        self.assertTrue(finished.failed)
        self.assertIs(finished.phases["ExclusiveB"], MissionPhase.STOPPED)

    def test_parallel_start_event_can_stop_group_before_children_launch(self) -> None:
        children: list[IdleMission] = []

        def factory(_mission_type: type[Mission]) -> Mission:
            mission = IdleMission()
            children.append(mission)
            return mission

        with MissionEngine(mission_factory=factory, scheduler_interval=0.001) as engine:
            engine.events.subscribe(
                lambda event: engine.stop_parallel(event.fields["execution_id"]),
                predicate=lambda event: event.event_type is MissionEventType.PARALLEL
                and event.message.startswith("Parallel execution started"),
                times=1,
            )
            run = engine.start_parallel(
                MissionParallelGroup(
                    "reentrant-stop",
                    (
                        MissionNode("first", IdleMission),
                        MissionNode("second", IdleMission),
                    ),
                )
            )
            finished = engine.parallel_snapshot(run.execution_id)

        self.assertTrue(finished.stopped)
        self.assertTrue(all(not child.started.is_set() for child in children))

    def test_registered_mission_can_terminate_without_starting(self) -> None:
        with MissionEngine(scheduler_interval=0.001) as engine:
            stopped = IdleMission()
            cancelled = IdleMission()
            engine.register(stopped)
            engine.register(cancelled)
            self.assertIs(
                engine.stop_mission(stopped).phase,
                MissionPhase.STOPPED,
            )
            self.assertIs(engine.cancel(cancelled).phase, MissionPhase.CANCELLED)
            self.assertFalse(stopped.started.is_set())
            self.assertFalse(cancelled.started.is_set())

    def test_chain_parallel_stage_passes_combined_result(self) -> None:
        stage = MissionParallelStage(
            "work",
            (MissionNode("left", ParallelA), MissionNode("right", ParallelB)),
        )
        with MissionEngine(scheduler_interval=0.001) as engine:
            run = engine.start_chain(
                MissionChain("mixed", (ProducerMission, stage, ParallelConsumer)),
                input={"value": 5},
            )
            wait_until(lambda: not engine.chain_snapshot(run.execution_id).active)
            finished = engine.chain_snapshot(run.execution_id)

        self.assertTrue(finished.completed)
        self.assertEqual(ParallelConsumer.received["left"]["a"], 1)  # type: ignore[index]
        self.assertEqual(ParallelConsumer.received["right"]["b"], 2)  # type: ignore[index]

    def test_failed_parallel_stage_does_not_advance_default_chain(self) -> None:
        stage = MissionParallelStage(
            "failed-work",
            (
                MissionNode("failure", FailingMission),
                MissionNode("success", ProducerMission),
            ),
        )
        with MissionEngine(scheduler_interval=0.001) as engine:
            run = engine.start_chain(
                MissionChain("failed-stage", (stage, NeverStartedMission)),
                input={"value": 1},
            )
            wait_until(lambda: not engine.chain_snapshot(run.execution_id).active)
            finished = engine.chain_snapshot(run.execution_id)

        self.assertTrue(finished.failed)
        self.assertFalse(NeverStartedMission.started.is_set())

    def test_background_owner_policies_and_failure_propagation(self) -> None:
        owner = IdleMission()
        background = IdleMission()
        with MissionEngine(scheduler_interval=0.001) as engine:
            engine.launch(owner)
            owner.started.wait(1.0)
            engine.launch_background(background, owner=owner)
            background.started.wait(1.0)
            engine.complete(owner, {"done": True})
            wait_until(lambda: engine.snapshot(background).phase.terminal)
            self.assertIs(engine.snapshot(background).phase, MissionPhase.STOPPED)

        owner = IdleMission()
        background = IdleMission()
        with MissionEngine(scheduler_interval=0.001) as engine:
            engine.launch(owner)
            owner.started.wait(1.0)
            engine.launch_background(
                background,
                owner=owner,
                termination_policy=OwnerTerminationPolicy.KEEP_RUNNING,
            )
            engine.complete(owner)
            self.assertTrue(engine.snapshot(background).phase.active)
            engine.stop_mission(background)

        owner = IdleMission()
        with MissionEngine(scheduler_interval=0.001) as engine:
            engine.launch(owner)
            owner.started.wait(1.0)
            failing = FailingMission()
            engine.launch_background(
                failing,
                owner=owner,
                failure_policy=BackgroundFailurePolicy.FAIL_OWNER,
            )
            wait_until(lambda: engine.snapshot(owner).phase.terminal)
            self.assertIs(engine.snapshot(owner).phase, MissionPhase.FAILED)

    def test_background_registration_rechecks_owner_atomically(self) -> None:
        owner = IdleMission()
        background = IdleMission()
        with MissionEngine(scheduler_interval=0.001) as engine:
            engine.launch(owner)
            self.assertTrue(owner.started.wait(1.0))
            engine.events.subscribe(
                lambda _event: engine.stop_mission(owner),
                predicate=lambda event: event.mission_id == background.id
                and event.message.startswith("Mission registered:"),
                times=1,
            )

            with self.assertRaises(MissionConflictError):
                engine.launch_background(background, owner=owner)

            self.assertIs(engine.snapshot(owner).phase, MissionPhase.STOPPED)
            self.assertNotIn(
                background.id,
                {snapshot.mission_id for snapshot in engine.snapshots()},
            )

    def test_background_cancel_policy_and_engine_shutdown(self) -> None:
        owner = IdleMission()
        background = IdleMission()
        with MissionEngine(scheduler_interval=0.001) as engine:
            engine.launch(owner)
            owner.started.wait(1.0)
            engine.launch_background(
                background,
                owner=owner,
                termination_policy=OwnerTerminationPolicy.CANCEL_WITH_OWNER,
            )
            background.started.wait(1.0)
            engine.cancel(owner)
            wait_until(lambda: engine.snapshot(background).phase.terminal)
            self.assertIs(engine.snapshot(background).phase, MissionPhase.CANCELLED)

        owner = IdleMission()
        background = IdleMission()
        engine = MissionEngine(scheduler_interval=0.001)
        engine.start()
        engine.launch(owner)
        owner.started.wait(1.0)
        engine.launch_background(
            background,
            owner=owner,
            termination_policy=OwnerTerminationPolicy.KEEP_RUNNING,
        )
        background.started.wait(1.0)
        engine.close()
        self.assertTrue(background.stopped.is_set())


if __name__ == "__main__":
    unittest.main()
