from __future__ import annotations

import threading
import time
import unittest

from src.core.mission import (
    BackgroundFailurePolicy,
    Mission,
    MissionChain,
    MissionConflictError,
    MissionEngine,
    MissionEventType,
    MissionNode,
    MissionParallelGroup,
    MissionParallelStage,
    MissionPhase,
    MissionRetryPolicy,
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
