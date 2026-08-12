"""Small standard-library compatibility helpers for supported Python versions."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - exercised on Python 3.10
    class StrEnum(str, Enum):
        """Python 3.10 equivalent of :class:`enum.StrEnum`."""

        def __str__(self) -> str:
            return str(self.value)

        def __format__(self, format_spec: str) -> str:
            return format(str(self), format_spec)


try:
    from builtins import ExceptionGroup
except ImportError:  # pragma: no cover - exercised on Python 3.10
    class ExceptionGroup(Exception):
        """Carry multiple ordinary exceptions on Python 3.10."""

        def __init__(self, message: str, exceptions: Iterable[Exception]) -> None:
            self.message = str(message)
            self.exceptions = tuple(exceptions)
            if not self.exceptions:
                raise ValueError("ExceptionGroup requires at least one exception")
            if any(not isinstance(error, Exception) for error in self.exceptions):
                raise TypeError("ExceptionGroup accepts Exception instances only")
            super().__init__(self.message, self.exceptions)

        def __str__(self) -> str:
            count = len(self.exceptions)
            return f"{self.message} ({count} sub-exception{'s' if count != 1 else ''})"


__all__ = ["ExceptionGroup", "StrEnum"]
