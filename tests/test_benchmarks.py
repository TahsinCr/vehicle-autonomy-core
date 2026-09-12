from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from run_benchmarks import BenchmarkResult, _regressions, run_load_profile


class BenchmarkToolTests(unittest.TestCase):
    def test_combined_memory_load_reports_portable_per_message_metrics(self) -> None:
        result = run_load_profile("normal", storage="memory")

        self.assertEqual(result.messages, 2_000)
        self.assertGreater(result.throughput_per_second, 0)
        self.assertGreaterEqual(result.latency_p99_ns, result.latency_p50_ns)
        self.assertEqual(result.writer_failed_records, 0)

    def test_regression_comparison_matches_operations_by_stable_name(self) -> None:
        baseline = BenchmarkResult("events", "publish", 100, 100.0, 100.0, 1.0, 0.0, 64)
        reference = BenchmarkResult("events", "reference", 100, 100.0, 100.0, 1.0, 0.0, 64)
        reference_two = BenchmarkResult("events", "reference two", 100, 100.0, 100.0, 1.0, 0.0, 64)
        current = BenchmarkResult("events", "publish", 100, 151.0, 151.0, 1.51, 0.0, 64)
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
                _regressions([current, reference, reference_two], path, 50.0),
                ["events/publish: +51.0%"],
            )


if __name__ == "__main__":
    unittest.main()
