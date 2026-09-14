from __future__ import annotations

import inspect
import importlib
import json
import sys
import unittest
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
    """Return stable signatures for exported callables and their declared methods."""

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
            is_project_class = inspect.isclass(value) and getattr(
                value, "__module__", ""
            ).startswith("src.core")
            if inspect.isfunction(value) or (
                is_project_class and "__init__" in vars(value)
            ):
                try:
                    signatures[qualified_name] = str(inspect.signature(value))
                except (TypeError, ValueError):
                    pass
            if not is_project_class:
                continue
            for member_name, member in vars(value).items():
                if member_name.startswith("_"):
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


class PublicApiContractTests(unittest.TestCase):
    def test_exported_callable_signatures_are_intentional(self) -> None:
        expected = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            build_public_api(),
            expected,
            "Public API changed; inspect the readable contract diff and run "
            "`python tests/test_public_api.py --update` only for an intentional change",
        )


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        CONTRACT_PATH.write_text(
            json.dumps(build_public_api(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        unittest.main()
