from __future__ import annotations

import inspect
import importlib
import json
import re
import subprocess
import sys
import unittest
from enum import Enum
from functools import cached_property
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src import core
except ModuleNotFoundError:
    import run_benchmarks  # noqa: F401

    from src import core


CONTRACT_PATH = Path(__file__).with_name("public-api.json")


def build_public_api() -> dict[str, str]:
    """Return stable signatures for exported callables and reachable methods."""

    modules = (
        core,
        importlib.import_module("src.core.dependency"),
        importlib.import_module("src.core.events"),
        importlib.import_module("src.core.mavlink"),
        importlib.import_module("src.core.mission"),
    )
    signatures: dict[str, str] = {}
    for module in modules:
        for name in sorted(module.__all__):
            value = getattr(module, name)
            qualified_name = f"{module.__name__}.{name}"
            signatures[qualified_name] = "<export>"
            if inspect.isclass(value) and getattr(value, "_is_protocol", False):
                signatures[qualified_name] = "<protocol>"
            is_project_class = inspect.isclass(value) and getattr(
                value, "__module__", ""
            ).startswith("src.core")
            if signatures[qualified_name] != "<protocol>" and (
                inspect.isfunction(value)
                or (is_project_class and "__init__" in vars(value))
            ):
                try:
                    signatures[qualified_name] = str(inspect.signature(value))
                except (TypeError, ValueError):
                    pass
            if not is_project_class:
                continue
            if issubclass(value, Enum):
                for member_name, member in value.__members__.items():
                    signatures[f"{qualified_name}.{member_name}"] = (
                        f"<enum> {member.value!r}"
                    )
            members: dict[str, object] = {}
            for base in reversed(value.__mro__):
                if getattr(base, "__module__", "").startswith("src.core"):
                    members.update(vars(base))
            for member_name, member in members.items():
                if member_name.startswith("_"):
                    continue
                if isinstance(member, (property, cached_property)):
                    getter = member.fget if isinstance(member, property) else member.func
                    try:
                        signature = str(inspect.signature(getter))
                    except (TypeError, ValueError):
                        signature = "<?>"
                    signatures[f"{qualified_name}.{member_name}"] = (
                        f"<{type(member).__name__}> {signature}"
                    )
                    if isinstance(member, property):
                        if member.fset is not None:
                            signatures[f"{qualified_name}.{member_name}.setter"] = str(
                                inspect.signature(member.fset)
                            )
                        if member.fdel is not None:
                            signatures[f"{qualified_name}.{member_name}.deleter"] = str(
                                inspect.signature(member.fdel)
                            )
                    continue
                if isinstance(member, (classmethod, staticmethod)):
                    member = member.__func__
                if not inspect.isfunction(member):
                    continue
                try:
                    signatures[f"{qualified_name}.{member_name}"] = str(
                        inspect.signature(member)
                    )
                except (TypeError, ValueError):
                    pass
    return dict(sorted(signatures.items()))


def incompatible_api_changes(
    previous: dict[str, str],
    current: dict[str, str],
) -> tuple[str, ...]:
    """Return removed or signature-changed entries from a prior contract."""

    changes: list[str] = []
    for name, signature in previous.items():
        if name not in current:
            changes.append(f"removed: {name}")
        elif current[name] != signature:
            changes.append(
                f"changed: {name}: {signature} -> {current[name]}"
            )
    return tuple(changes)


def _project_version(document: str) -> tuple[int, int, int, bool]:
    match = re.search(
        r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)(\.dev\d*)?"',
        document,
        re.MULTILINE,
    )
    if match is None:
        raise ValueError(
            "Project version must use major.minor.patch or major.minor.patch.devN format"
        )
    major, minor, patch, development = match.groups()
    return int(major), int(minor), int(patch), development is not None


def check_patch_compatibility(tag: str) -> tuple[str, ...]:
    """Compare the current contract with a release tag when it is a patch line."""

    current_version = _project_version(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    previous_project = subprocess.run(
        ["git", "show", f"{tag}:pyproject.toml"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    previous_version = _project_version(previous_project)
    if current_version[3]:
        return ()
    if current_version[:2] != previous_version[:2]:
        return ()
    previous_contract = json.loads(
        subprocess.run(
            ["git", "show", f"{tag}:tests/public-api.json"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return incompatible_api_changes(previous_contract, build_public_api())


class PublicApiContractTests(unittest.TestCase):
    def test_development_versions_are_recognized_explicitly(self) -> None:
        self.assertEqual(_project_version('version = "1.8.3"'), (1, 8, 3, False))
        self.assertEqual(_project_version('version = "1.8.3.dev0"'), (1, 8, 3, True))
        self.assertEqual(_project_version('version = "1.8.3.dev2"'), (1, 8, 3, True))

    def test_patch_compatibility_allows_additions_but_rejects_breakage(self) -> None:
        previous = {"module.call": "(value: int) -> str"}
        self.assertEqual(
            incompatible_api_changes(
                previous,
                {**previous, "module.new_call": "() -> None"},
            ),
            (),
        )
        self.assertEqual(
            incompatible_api_changes(
                previous,
                {"module.call": "(value: str) -> str"},
            ),
            (
                "changed: module.call: (value: int) -> str -> "
                "(value: str) -> str",
            ),
        )

    def test_exported_callable_signatures_are_intentional(self) -> None:
        expected = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            build_public_api(),
            expected,
            "Public API changed; inspect the readable contract diff and run "
            "`python tests/test_public_api.py --update` only for an intentional change",
        )

    def test_public_properties_are_part_of_the_contract(self) -> None:
        contract = build_public_api()
        self.assertTrue(
            contract["src.core.mavlink.MavlinkVehicle.state"].startswith(
                "<property>"
            )
        )

    def test_public_enum_members_and_values_are_part_of_the_contract(self) -> None:
        contract = build_public_api()
        self.assertEqual(
            contract["src.core.mission.MissionPhase.RUNNING"],
            "<enum> 'running'",
        )


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        CONTRACT_PATH.write_text(
            json.dumps(build_public_api(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif len(sys.argv) == 3 and sys.argv[1] == "--check-patch-compatible":
        changes = check_patch_compatibility(sys.argv[2])
        if changes:
            print("Patch release contains incompatible public API changes:", file=sys.stderr)
            for change in changes:
                print(f"- {change}", file=sys.stderr)
            raise SystemExit(1)
    else:
        unittest.main()
