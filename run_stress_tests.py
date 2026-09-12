"""Repeat the core's highest-risk concurrency and lifecycle regressions."""

from __future__ import annotations

import argparse
import io
import sys
import time
import unittest


STRESS_TESTS = (
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_concurrent_shutdown_disposes_a_resource_once",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_concurrent_shutdown_callers_receive_the_same_failure",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_cross_thread_initialization_cycle_fails_instead_of_deadlocking",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_inflight_unregister_reserves_token_and_is_one_barrier",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_registration_cannot_commit_after_shutdown_claim",
    "tests.dependency.test_lifecycle.AsyncDependencyLifecycleTests."
    "test_cross_task_cached_provider_cycle_is_detected",
    "tests.events.test_bus.EventBusTests."
    "test_close_reports_a_stuck_periodic_schedule",
    "tests.events.test_bus.EventBusTests."
    "test_close_waits_for_periodic_thread_exit",
    "tests.mavlink.test_runtime.MavlinkRuntimeTests."
    "test_concurrent_close_waits_for_cleanup",
    "tests.mavlink.test_runtime.AsyncMavlinkRuntimeTests."
    "test_repeated_cancellation_keeps_blocking_io_owned",
    "tests.mavlink.test_runtime.AsyncMavlinkRuntimeTests."
    "test_concurrent_close_waits_for_the_same_cleanup",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_callback_completion_intent_survives_cleanup_failure",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_callback_failure_retry_intent_survives_cleanup_failure",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_uncaught_exception_intent_survives_cleanup_failure",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_external_failure_retry_intent_survives_cleanup_failure",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_stop_waits_for_tick_before_cleanup",
)


def run(repeats: int, *, verbosity: int = 0) -> bool:
    """Run a fresh instance of every stress test for each repetition."""

    if isinstance(repeats, bool) or repeats < 1:
        raise ValueError("Stress repetitions must be a positive integer")
    started = time.perf_counter()
    for iteration in range(1, repeats + 1):
        suite = unittest.defaultTestLoader.loadTestsFromNames(STRESS_TESTS)
        output = None if verbosity else io.StringIO()
        result = unittest.TextTestRunner(
            stream=output,
            verbosity=verbosity,
        ).run(suite)
        if not result.wasSuccessful():
            if output is not None:
                print(output.getvalue(), file=sys.stderr)
            print(f"Stress run failed at repetition {iteration}/{repeats}")
            return False
    elapsed = time.perf_counter() - started
    total = repeats * len(STRESS_TESTS)
    print(f"Stress checks passed: {total} executions in {elapsed:.2f}s")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=25)
    parser.add_argument("--verbose", action="store_true")
    arguments = parser.parse_args()
    return 0 if run(arguments.repeats, verbosity=2 if arguments.verbose else 0) else 1


if __name__ == "__main__":
    sys.exit(main())
