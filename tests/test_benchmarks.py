from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

import run_benchmarks


class BenchmarkToolTests(unittest.TestCase):
    def test_combined_memory_load_reports_portable_per_message_metrics(self) -> None:
        result = run_benchmarks.run_load_profile("normal", storage="memory")

        self.assertEqual(result.messages, 2_000)
        self.assertGreater(result.throughput_per_second, 0)
        self.assertGreaterEqual(result.latency_p99_ns, result.latency_p50_ns)
        self.assertEqual(result.writer_failed_records, 0)

    def test_regression_comparison_matches_operations_by_stable_name(self) -> None:
        baseline = run_benchmarks.BenchmarkResult(
            "events", "publish", 100, 100.0, 100.0, 1.0, 0.0, 64
        )
        reference = run_benchmarks.BenchmarkResult(
            "events", "reference", 100, 100.0, 100.0, 1.0, 0.0, 64
        )
        reference_two = run_benchmarks.BenchmarkResult(
            "events", "reference two", 100, 100.0, 100.0, 1.0, 0.0, 64
        )
        anchor = run_benchmarks.BenchmarkResult(
            "baseline", "function call", 100, 100.0, 100.0, 1.0, 0.0, 64
        )
        current = run_benchmarks.BenchmarkResult(
            "events", "publish", 100, 151.0, 151.0, 1.51, 0.0, 64
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(
                json.dumps(
                    {
                        "results": [
                            asdict(baseline),
                            asdict(reference),
                            asdict(reference_two),
                            asdict(anchor),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                run_benchmarks._regressions(
                    [current, reference, reference_two, anchor], path, 50.0
                ),
                ["events/publish: +51.0%"],
            )

    def test_regression_comparison_detects_suite_wide_library_slowdown(self) -> None:
        anchor = run_benchmarks.BenchmarkResult(
            "baseline", "function call", 100, 100.0, 100.0, 1.0, 0.0, 1
        )
        previous = run_benchmarks.BenchmarkResult(
            "events", "publish", 100, 100.0, 100.0, 1.0, 0.0, 1
        )
        current = run_benchmarks.BenchmarkResult(
            "events", "publish", 100, 150.0, 150.0, 1.5, 0.0, 1
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(
                json.dumps({"results": [asdict(anchor), asdict(previous)]}),
                encoding="utf-8",
            )
            self.assertEqual(
                run_benchmarks._regressions([anchor, current], path, 35.0),
                ["events/publish: +50.0%"],
            )

    def test_regression_comparison_rejects_insufficient_operation_coverage(self) -> None:
        anchor = run_benchmarks.BenchmarkResult(
            "baseline", "function call", 100, 100.0, 100.0, 1.0, 0.0, 1
        )
        current = run_benchmarks.BenchmarkResult(
            "events", "publish", 100, 100.0, 100.0, 1.0, 0.0, 1
        )
        baseline_results = [asdict(anchor), asdict(current)]
        baseline_results.extend(
            {
                **asdict(current),
                "name": f"removed operation {index}",
            }
            for index in range(4)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(
                json.dumps({"results": baseline_results}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "fewer than 80%"):
                run_benchmarks._regressions([anchor, current], path, 35.0)

    def test_load_regression_compares_portable_costs(self) -> None:
        current = run_benchmarks.LoadBenchmarkResult(
            "test", 1, 1, 1, "sqlite", 70.0, 1.0, 1.0, 140.0,
            140.0, 1.0, 1.0, 0, 0, 0,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "load.json"
            path.write_text(
                json.dumps(
                    {
                        "throughput_per_second": 100.0,
                        "latency_p99_ns": 100.0,
                        "cpu_ns_per_message": 100.0,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                run_benchmarks._load_regressions(current, path, 35.0),
                ["throughput: +42.9%", "latency p99: +40.0%", "CPU per message: +40.0%"],
            )

    def test_load_regression_does_not_fail_on_isolated_p99_jitter(self) -> None:
        current = run_benchmarks.LoadBenchmarkResult(
            "test", 1, 1, 1, "sqlite", 100.0, 1.0, 1.0, 160.0,
            100.0, 1.0, 1.0, 0, 0, 0,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "load.json"
            path.write_text(
                json.dumps(
                    {
                        "throughput_per_second": 100.0,
                        "latency_p99_ns": 100.0,
                        "cpu_ns_per_message": 100.0,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                run_benchmarks._load_regressions(current, path, 35.0),
                [],
            )

    def test_repeated_load_profile_reports_median_costs(self) -> None:
        samples = [
            run_benchmarks.LoadBenchmarkResult(
                "test", 1, 1, 1, "sqlite", throughput, 1.0, 2.0, latency,
                cpu, 4.0, 5.0, queued, failed, threads,
            )
            for throughput, latency, cpu, queued, failed, threads in (
                (100.0, 30.0, 300.0, 2, 0, 0),
                (300.0, 10.0, 100.0, 8, 1, 0),
                (200.0, 20.0, 200.0, 4, 0, 1),
            )
        ]
        with mock.patch.object(
            run_benchmarks,
            "run_load_profile",
            side_effect=samples,
        ):
            result = run_benchmarks.run_load_profiles("test", repeats=3)

        self.assertEqual(result.throughput_per_second, 200.0)
        self.assertEqual(result.latency_p99_ns, 20.0)
        self.assertEqual(result.cpu_ns_per_message, 200.0)
        self.assertEqual(result.writer_max_queued, 8)
        self.assertEqual(result.writer_failed_records, 1)
        self.assertEqual(result.thread_delta, 1)

    def test_log_appends_versioned_run_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark-logs.json"
            run_benchmarks._append_benchmark_log(
                path, mode="test", result={"sample": 1}, status="passed"
            )
            run_benchmarks._append_benchmark_log(
                path, mode="test", result={"sample": 2}, status="passed"
            )

            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], 1)
            self.assertEqual(len(document["runs"]), 2)
            self.assertTrue(document["runs"][0]["timestamp"])
            self.assertTrue(document["runs"][0]["version"])
            self.assertTrue(document["runs"][0]["commit"])
            self.assertEqual(
                document["runs"][0]["version"],
                run_benchmarks._project_version(),
            )

    def test_load_acceptance_rejects_loss_and_thread_leaks(self) -> None:
        result = run_benchmarks.LoadBenchmarkResult(
            "test", 1, 1, 1, "sqlite", 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 0, 2, 1,
        )
        self.assertEqual(len(run_benchmarks._load_failures(result)), 2)


if __name__ == "__main__":
    unittest.main()
