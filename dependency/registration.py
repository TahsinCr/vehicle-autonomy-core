"""Dependency tokens, lifetimes, markers, and provider registrations."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeAlias, TypeVar

from ..compatibility import StrEnum


T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")
Token: TypeAlias = Hashable | type[Any]
ProviderCallable: TypeAlias = Callable[..., Any]
TypedProvider: TypeAlias = type[T] | Callable[..., T]
DependencyMap: TypeAlias = Mapping[str, Token]

DEFAULT_PRIORITY = 100
NONE_TYPE = type(None)


class _Missing:
    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


class InitializationGate:
    """Coordinate one cached value across sync threads and async tasks."""

    __slots__ = ("_condition", "_initializing")

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._initializing = False

    def claim(self) -> bool:
        with self._condition:
            if self._initializing:
                return False
            self._initializing = True
            return True

    def wait(self) -> None:
        with self._condition:
            self._condition.wait_for(lambda: not self._initializing)

    async def wait_async(self) -> None:
        await asyncio.to_thread(self.wait)

    def release(self) -> None:
        with self._condition:
            self._initializing = False
            self._condition.notify_all()


class Lifetime(StrEnum):
    TRANSIENT = "transient"
    SINGLETON = "singleton"
    SCOPED = "scoped"


@dataclass(frozen=True, slots=True)
class Inject:
    """Explicitly mark a parameter for dependency injection."""

    token: Any = MISSING
    optional: bool = False


@dataclass(slots=True)
class Provider:
    token: Token
    factory: Any
    lifetime: Lifetime
    dependencies: dict[str, Token] = field(default_factory=dict)
    priority: int = DEFAULT_PRIORITY
    instance: Any = MISSING
    singleton: Any = MISSING
    initialization: InitializationGate = field(default_factory=InitializationGate)

    @property
    def has_instance(self) -> bool:
        return self.instance is not MISSING

@dataclass(frozen=True, slots=True)
class Registration:
    token: Token
    factory: Any
    lifetime: Lifetime
    dependencies: dict[str, Token]
    priority: int
    instance: Any = MISSING
