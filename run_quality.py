"""Run the local quality gate against the supported Python 3.10 type target."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent


def build_commands(
    target_python: Path,
    *,
    include_tests: bool,
    include_coverage: bool,
) -> tuple[tuple[str, ...], ...]:
    """Build the ordered quality checks without executing them."""

    commands: list[tuple[str, ...]] = [
        (str(target_python), "-m", "ruff", "check", "."),
        (str(target_python), "-m", "pyright", "--pythonpath", str(target_python)),
        (str(target_python), "-m", "compileall", "-q", "."),
        (str(target_python), "tests/test_public_api.py"),
    ]
    if include_coverage:
        commands.extend(
            (
                (str(target_python), "-m", "coverage", "run", "run_tests.py"),
                (str(target_python), "-m", "coverage", "report"),
            )
        )
    elif include_tests:
        commands.append((str(target_python), "run_tests.py"))
    return tuple(commands)


def resolve_python(command: str) -> Path:
    """Resolve and verify an exact Python 3.10 interpreter."""

    resolved = shutil.which(command)
    if resolved is None:
        candidate = Path(command).expanduser()
        if candidate.is_file():
            resolved = str(candidate)
    if resolved is None and command == "python3.10":
        resolved = _resolve_pyenv_python_310()
    if resolved is None:
        raise RuntimeError(
            f"Python interpreter {command!r} was not found. "
            "Install Python 3.10 or pass --python /path/to/python3.10."
        )
    target = Path(resolved).resolve()
    version = _python_version(target)
    if version != "3.10" and command == "python3.10":
        pyenv_python = _resolve_pyenv_python_310()
        if pyenv_python is not None:
            target = Path(pyenv_python).resolve()
            version = _python_version(target)
    if version != "3.10":
        raise RuntimeError(
            f"Quality checks require Python 3.10; {target} reports {version or 'unavailable'}."
        )
    return target


def _python_version(target: Path) -> str:
    """Return an interpreter's major/minor version without raising."""

    completed = subprocess.run(
        [str(target), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _resolve_pyenv_python_310() -> str | None:
    """Find the newest installed Python 3.10 managed by pyenv, if available."""

    pyenv = shutil.which("pyenv")
    if pyenv is None:
        return None
    listed = subprocess.run(
        [pyenv, "versions", "--bare"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if listed.returncode:
        return None
    candidates = [
        line.strip()
        for line in listed.stdout.splitlines()
        if line.strip().startswith("3.10.")
    ]
    if not candidates:
        return None
    version = max(candidates, key=_version_key)
    prefix = subprocess.run(
        [pyenv, "prefix", version],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if prefix.returncode:
        return None
    candidate = Path(prefix.stdout.strip()) / "bin" / "python"
    return str(candidate) if candidate.is_file() else None


def _version_key(value: str) -> tuple[int, ...]:
    """Sort plain Python version strings numerically."""

    return tuple(int(part) for part in value.split("."))


def run(commands: Sequence[Sequence[str]]) -> int:
    """Run commands in order and stop at the first failed quality gate."""

    for command in commands:
        print(f"+ {shlex.join(command)}", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default="python3.10",
        help="Exact Python 3.10 interpreter to use (default: python3.10).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--tests",
        action="store_true",
        help="Also run the full unittest suite after static checks.",
    )
    mode.add_argument(
        "--coverage",
        action="store_true",
        help="Run the full suite with the configured branch-coverage gate.",
    )
    arguments = parser.parse_args(argv)
    try:
        target_python = resolve_python(arguments.python)
    except RuntimeError as error:
        parser.error(str(error))
    return run(
        build_commands(
            target_python,
            include_tests=arguments.tests,
            include_coverage=arguments.coverage,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
