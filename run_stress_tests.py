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
    "test_sync_cleanup_reentrancy_fails_instead_of_deadlocking",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_cross_thread_initialization_cycle_fails_instead_of_deadlocking",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_inflight_unregister_reserves_token_and_is_one_barrier",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_autowire_cannot_bypass_class_token_disposal",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_late_unregister_cannot_escape_shutdown_admission",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_registration_cannot_commit_after_shutdown_claim",
    "tests.dependency.test_lifecycle.DependencyLifecycleTests."
    "test_new_instance_cannot_commit_after_shutdown_claim",
    "tests.dependency.test_lifecycle.AsyncDependencyLifecycleTests."
    "test_cross_task_cached_provider_cycle_is_detected",
    "tests.dependency.test_lifecycle.AsyncDependencyLifecycleTests."
    "test_sync_and_async_unregister_share_one_disposal_attempt",
    "tests.dependency.test_lifecycle.AsyncDependencyLifecycleTests."
    "test_async_cleanup_reentrancy_fails_instead_of_deadlocking",
    "tests.dependency.test_lifecycle.AsyncDependencyLifecycleTests."
    "test_token_disposal_cannot_start_container_shutdown",
    "tests.dependency.test_lifecycle.AsyncDependencyLifecycleTests."
    "test_completed_cleanup_marker_does_not_reject_child_task",
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
    "test_tick_exception_intent_survives_cleanup_failure",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_terminal_commit_rejects_competing_commands_during_cleanup",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_cleanup_terminal_commands_do_not_reenter_finalization",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_cleanup_hook_cannot_reenter_matching_failure_finalization",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_cleanup_child_thread_cannot_reenter_terminalization",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_external_matching_terminal_commands_wait_for_cleanup",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_cleanup_retry_cannot_reenter_matching_completion",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_pause_and_resume_can_request_terminal_commands",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_callback_error_during_external_stop_is_reported_without_replacing_intent",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_retry_generation_starts_without_stale_terminal_intent",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_self_stop_unwinds_callback_before_cleanup_and_release",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_self_cancel_unwinds_tick_before_cleanup",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_cancel_intent_survives_cleanup_failure_and_rejects_stop",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_stop_waits_for_tick_before_cleanup",
    "tests.mission.test_engine.MissionEngineLifecycleTests."
    "test_unregister_waits_for_terminal_worker_finalization",
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
