"""Regression coverage for the local Python 3.10 quality runner."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_quality


class QualityRunnerTests(unittest.TestCase):
    def test_default_quality_commands_target_python_310(self) -> None:
        target = Path("/usr/bin/python3.10")

        commands = run_quality.build_commands(
            target,
            include_tests=False,
            include_coverage=False,
        )

        self.assertEqual(commands[0], (str(target), "-m", "ruff", "check", "."))
        self.assertEqual(
            commands[1],
            (str(target), "-m", "pyright", "--pythonpath", str(target)),
        )
        self.assertEqual(commands[2], (str(target), "-m", "compileall", "-q", "."))
        self.assertEqual(commands[3], (str(target), "tests/test_public_api.py"))

    def test_coverage_mode_owns_the_full_test_run(self) -> None:
        target = Path("/usr/bin/python3.10")

        commands = run_quality.build_commands(
            target,
            include_tests=False,
            include_coverage=True,
        )

        self.assertEqual(
            commands[-2:],
            (
                (str(target), "-m", "coverage", "run", "run_tests.py"),
                (str(target), "-m", "coverage", "report"),
            ),
        )

    def test_pyenv_version_ordering_prefers_the_latest_python_310(self) -> None:
        self.assertEqual(
            max(("3.10.12", "3.10.18"), key=run_quality._version_key),
            "3.10.18",
        )

    def test_resolve_python_accepts_an_exact_python_310(self) -> None:
        with (
            patch.object(run_quality.shutil, "which", return_value="/opt/python3.10"),
            patch.object(run_quality, "_python_version", return_value="3.10"),
        ):
            target = run_quality.resolve_python("python3.10")

        self.assertEqual(target, Path("/opt/python3.10"))

    def test_resolve_python_falls_back_from_an_inactive_pyenv_shim(self) -> None:
        with (
            patch.object(run_quality.shutil, "which", return_value="/pyenv/shims/python3.10"),
            patch.object(
                run_quality,
                "_python_version",
                side_effect=("", "3.10"),
            ),
            patch.object(
                run_quality,
                "_resolve_pyenv_python_310",
                return_value="/pyenv/versions/3.10.18/bin/python3.10",
            ),
        ):
            target = run_quality.resolve_python("python3.10")

        self.assertEqual(target, Path("/pyenv/versions/3.10.18/bin/python3.10"))

    def test_resolve_python_uses_pyenv_when_python310_is_not_on_path(self) -> None:
        with (
            patch.object(run_quality.shutil, "which", return_value=None),
            patch.object(
                run_quality,
                "_resolve_pyenv_python_310",
                return_value="/pyenv/versions/3.10.18/bin/python3.10",
            ),
            patch.object(run_quality, "_python_version", return_value="3.10"),
        ):
            target = run_quality.resolve_python("python3.10")

        self.assertEqual(target, Path("/pyenv/versions/3.10.18/bin/python3.10"))

    def test_run_stops_after_the_first_failed_gate(self) -> None:
        commands = (("first",), ("second",), ("third",))
        with patch.object(
            run_quality.subprocess,
            "run",
            side_effect=(SimpleNamespace(returncode=0), SimpleNamespace(returncode=7)),
        ) as mocked_run:
            result = run_quality.run(commands)

        self.assertEqual(result, 7)
        self.assertEqual(mocked_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
