"""Package layout and project metadata checks."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageLayoutTests(unittest.TestCase):
    """Verify the two package layouts supported by the core."""

    def _copy_as_package(self, package_name: str, destination: Path) -> Path:
        parts = package_name.split(".")
        package = destination.joinpath(*parts)
        package.parent.mkdir(parents=True)

        current = destination
        for part in parts[:-1]:
            current /= part
            (current / "__init__.py").touch()

        shutil.copytree(
            ROOT,
            package,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "python",
                "__pycache__",
                "*.pyc",
            ),
        )
        return package

    def _assert_package_layout(self, package_name: str) -> None:
        check = """
import importlib
import sys

package_name = sys.argv[1]
core = importlib.import_module(package_name)
dependency = importlib.import_module(f"{package_name}.dependency")
mission = importlib.import_module(f"{package_name}.mission")
mavlink = importlib.import_module(f"{package_name}.mavlink")

assert core.DependencyContainer is dependency.DependencyContainer
assert core.MissionEngine is mission.MissionEngine
assert core.MissionLifecycle is mission.MissionLifecycle
assert core.MissionScheduler is mission.MissionScheduler
assert not issubclass(mission.MissionEngine, mission.MissionLifecycle)
assert not issubclass(mission.MissionEngine, mission.MissionScheduler)
assert mavlink.MavlinkEndpoint.udp("127.0.0.1", 14550).uri == "udp:127.0.0.1:14550"
assert mavlink.MavlinkRuntime.__name__ == "MavlinkRuntime"
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            self._copy_as_package(package_name, package_root)
            completed = subprocess.run(
                [sys.executable, "-c", check, package_name],
                cwd=package_root,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_intended_src_core_layout(self) -> None:
        self._assert_package_layout("src.core")

    def test_relative_imports_allow_another_parent_package(self) -> None:
        self._assert_package_layout("vehicle_stack.core")


class ProjectMetadataTests(unittest.TestCase):
    """Keep install metadata and repository naming consistent."""

    def test_mavlink_remains_an_optional_dependency(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertEqual(project["dependencies"], [])
        self.assertIn("pymavlink", project["optional-dependencies"]["mavlink"][0])

    def test_repository_contains_no_legacy_project_spelling(self) -> None:
        searchable_suffixes = {".md", ".py", ".toml"}
        legacy_spelling = "auth" + "onomy"
        offenders: list[str] = []
        for path in ROOT.rglob("*"):
            if (
                not path.is_file()
                or path.suffix not in searchable_suffixes
                or any(part in {".git", "python", "__pycache__"} for part in path.parts)
            ):
                continue
            if legacy_spelling in path.read_text(encoding="utf-8").casefold():
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
