from __future__ import annotations

import subprocess
import sys
import textwrap
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageImportTests(unittest.TestCase):
    def _assert_package_imports(self, package_name: str) -> None:
        script = textwrap.dedent(
            """
            import importlib.util
            import pathlib
            import sys
            import types

            root = pathlib.Path(sys.argv[1])
            package_name = sys.argv[2]
            parent_name = package_name.rpartition('.')[0]
            if parent_name:
                parent = types.ModuleType(parent_name)
                parent.__path__ = []
                sys.modules[parent_name] = parent

            spec = importlib.util.spec_from_file_location(
                package_name,
                root / '__init__.py',
                submodule_search_locations=[str(root)],
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)

            dependency = __import__(package_name + '.dependency', fromlist=['DependencyContainer'])
            errors = __import__(package_name + '.dependency.errors', fromlist=['DependencyError'])
            mission = __import__(package_name + '.mission', fromlist=['Mission'])
            mavlink = __import__(package_name + '.mavlink', fromlist=['MavlinkEndpoint'])
            assert module.DependencyContainer is dependency.DependencyContainer
            assert dependency.DependencyError is errors.DependencyError
            assert dependency.DependencyContainer.__module__ == package_name + '.dependency'
            assert dependency.injection.__module__ == package_name + '.dependency'
            assert mission.Mission.__module__ == package_name + '.mission'
            assert mission.MissionTransitionError.__module__ == package_name + '.mission'
            assert module.EventEngine.__name__ == 'EventEngine'
            assert module.AsyncEventEngine.__name__ == 'AsyncEventEngine'
            assert module.MissionEngine is mission.MissionEngine
            assert module.MissionLifecycle is mission.MissionLifecycle
            assert module.MissionScheduler is mission.MissionScheduler
            assert not issubclass(mission.MissionEngine, mission.MissionLifecycle)
            assert not issubclass(mission.MissionEngine, mission.MissionScheduler)
            assert mavlink.MavlinkEndpoint.udp('127.0.0.1', 14550).uri == 'udp:127.0.0.1:14550'
            assert mavlink.MavlinkRuntime.__name__ == 'MavlinkRuntime'
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), package_name],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_src_core_imports_remain_supported(self) -> None:
        self._assert_package_imports("src.core")

    def test_package_imports_work_under_another_parent(self) -> None:
        self._assert_package_imports("vehicle_stack.core")

    def test_project_metadata_keeps_mavlink_optional(self) -> None:
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
