"""Test bootstrap for both standalone and ``src/core`` source layouts."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_standalone_checkout() -> None:
    if "src.core" in sys.modules:
        return

    root = Path(__file__).resolve().parents[1]
    src = sys.modules.get("src")
    if src is None:
        src = types.ModuleType("src")
        src.__path__ = []  # type: ignore[attr-defined]
        sys.modules["src"] = src

    spec = importlib.util.spec_from_file_location(
        "src.core",
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the standalone core checkout")
    module = importlib.util.module_from_spec(spec)
    sys.modules["src.core"] = module
    spec.loader.exec_module(module)


_load_standalone_checkout()
