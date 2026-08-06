"""Dependency tokens, lifetimes, markers, and provider registrations."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ParamSpec, TypeAlias, TypeVar


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
    sync_lock: threading.RLock = field(default_factory=threading.RLock)
    async_lock: asyncio.Lock | None = None

    @property
    def has_instance(self) -> bool:
        return self.instance is not MISSING

    def get_async_lock(self) -> asyncio.Lock:
        if self.async_lock is None:
            self.async_lock = asyncio.Lock()
        return self.async_lock


@dataclass(frozen=True, slots=True)
class Registration:
    token: Token
    factory: Any
    lifetime: Lifetime
    dependencies: dict[str, Token]
    priority: int
    instance: Any = MISSING
