"""Keep the hand-written documentation connected to the supported public API."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class DocumentationTests(unittest.TestCase):
    def test_every_public_export_is_documented(self) -> None:
        exports_by_module: dict[str, list[str]] = {}
        for relative in self._public_modules():
            exports_by_module[relative] = self._exports(relative)

        missing: dict[str, list[str]] = {}
        for language in ("en", "tr"):
            documentation = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (DOCS / language).glob("*.md")
            )
            for relative, exports in exports_by_module.items():
                absent = [name for name in exports if name not in documentation]
                if absent:
                    missing[f"{language}:{relative}"] = absent
        self.assertEqual(missing, {})

    def test_local_markdown_links_resolve(self) -> None:
        broken: list[tuple[str, str]] = []
        pages = (ROOT / "README.md", ROOT / "README-TR.md", *DOCS.rglob("*.md"))
        for page in pages:
            content = page.read_text(encoding="utf-8")
            content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            content = re.sub(r"`[^`]*`", "", content)
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", content):
                path = target.split("#", 1)[0]
                if not path or "://" in path or path.startswith("mailto:"):
                    continue
                if not (page.parent / path).resolve().exists():
                    broken.append((str(page.relative_to(ROOT)), target))
        self.assertEqual(broken, [])

    def test_every_topic_has_a_language_switch(self) -> None:
        missing: list[str] = []
        for language, counterpart in (("en", "Türkçe"), ("tr", "English")):
            for page in (DOCS / language).glob("*.md"):
                header = page.read_text(encoding="utf-8").splitlines()[0]
                if counterpart not in header or "github.com/TahsinCr/vehicle-autonomy-core" not in header:
                    missing.append(str(page.relative_to(ROOT)))
        self.assertEqual(missing, [])

    @staticmethod
    def _public_modules() -> tuple[str, ...]:
        return (
            "__init__.py",
            "dependency/__init__.py",
            "events/__init__.py",
            "mission/__init__.py",
            "mavlink/__init__.py",
        )

    @staticmethod
    def _exports(relative: str) -> list[str]:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        exports: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                continue
            try:
                exports.extend(ast.literal_eval(node.value))
            except (TypeError, ValueError):
                continue
        return exports


if __name__ == "__main__":
    unittest.main()
