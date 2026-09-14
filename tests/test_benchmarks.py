from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

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
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                run_benchmarks._regressions(
                    [current, reference, reference_two], path, 50.0
                ),
                ["events/publish: +51.0%"],
            )

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
