"""Cached-resource ownership and deterministic disposal."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any

from .registration import MISSING, Provider
from .errors import AsyncDependencyError
from .resolution import close_awaitable, format_token, maybe_await


class ResourceTracker:
    def __init__(self) -> None:
        self._creation_order: list[Any] = []

    def remember(self, instance: Any) -> None:
        if instance is not MISSING and not any(
            item is instance for item in self._creation_order
        ):
            self._creation_order.append(instance)

    def ordered(self, candidates: Iterable[Any]) -> tuple[Any, ...]:
        values = tuple(item for item in candidates if item is not MISSING)
        active_ids = {id(item) for item in values}
        ordered: list[Any] = []
        seen: set[int] = set()
        for item in reversed(self._creation_order):
            identity = id(item)
            if identity in active_ids and identity not in seen:
                ordered.append(item)
                seen.add(identity)
        for item in reversed(values):
            identity = id(item)
            if identity not in seen:
                ordered.append(item)
                seen.add(identity)
        return tuple(ordered)

    def forget(self, instances: Iterable[Any]) -> None:
        identities = {id(instance) for instance in instances}
        self._creation_order = [
            item for item in self._creation_order if id(item) not in identities
        ]


def cached_instances(provider: Provider) -> tuple[Any, ...]:
    instances: list[Any] = []
    if provider.instance is not MISSING:
        instances.append(provider.instance)
    if provider.singleton is not MISSING:
        instances.append(provider.singleton)
    return tuple(instances)


def requires_async_disposal(instance: Any) -> bool:
    close = getattr(instance, "close", None)
    if callable(close):
        return inspect.iscoroutinefunction(close)
    return callable(getattr(instance, "aclose", None))


def dispose(instance: Any) -> None:
    close = getattr(instance, "close", None)
    if not callable(close):
        if callable(getattr(instance, "aclose", None)):
            raise AsyncDependencyError(
                f"{format_token(type(instance))}.aclose() async; "
                "unregister_async/shutdown_async kullan."
            )
        return
    if inspect.iscoroutinefunction(close):
        raise AsyncDependencyError(
            f"{format_token(type(instance))}.close() async; "
            "unregister_async/shutdown_async kullan."
        )
    result = close()
    if inspect.isawaitable(result):
        close_awaitable(result)
        raise AsyncDependencyError(
            f"{format_token(type(instance))}.close() async; "
            "unregister_async/shutdown_async kullan."
        )


async def dispose_async(instance: Any) -> None:
    aclose = getattr(instance, "aclose", None)
    if callable(aclose):
        await maybe_await(aclose())
        return
    close = getattr(instance, "close", None)
    if callable(close):
        await maybe_await(close())


def dispose_many(instances: Iterable[Any]) -> None:
    errors: list[Exception] = []
    seen: set[int] = set()
    for instance in instances:
        if instance is MISSING or id(instance) in seen:
            continue
        seen.add(id(instance))
        try:
            dispose(instance)
        except Exception as exc:
            errors.append(exc)
    raise_disposal_errors(errors)


async def dispose_many_async(instances: Iterable[Any]) -> None:
    errors: list[Exception] = []
    seen: set[int] = set()
    for instance in instances:
        if instance is MISSING or id(instance) in seen:
            continue
        seen.add(id(instance))
        try:
            await dispose_async(instance)
        except Exception as exc:
            errors.append(exc)
    raise_disposal_errors(errors)


def raise_disposal_errors(errors: Iterable[Exception]) -> None:
    collected = tuple(errors)
    if not collected:
        return
    if len(collected) == 1:
        raise collected[0]
    raise ExceptionGroup("Birden fazla dependency kaynağı kapatılamadı", collected)
