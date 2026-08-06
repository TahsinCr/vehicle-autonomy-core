"""Resolution-stack tracking and callable helpers."""

from __future__ import annotations

import contextvars
import inspect
from typing import Any

from .registration import Token
from .errors import CircularDependencyError


_resolution_stack: contextvars.ContextVar[tuple[Token, ...]] = contextvars.ContextVar(
    "dependency_resolution_stack",
    default=(),
)


def enter_resolution(token: Token) -> contextvars.Token[tuple[Token, ...]]:
    stack = _resolution_stack.get()
    if token in stack:
        cycle = " -> ".join(format_token(item) for item in (*stack, token))
        raise CircularDependencyError(f"Döngüsel dependency tespit edildi: {cycle}")
    return _resolution_stack.set((*stack, token))


def exit_resolution(stack_token: contextvars.Token[tuple[Token, ...]]) -> None:
    _resolution_stack.reset(stack_token)


def can_autowire(token: Any) -> bool:
    return (
        inspect.isclass(token)
        and token.__module__ != "builtins"
        and not inspect.isabstract(token)
    )


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def close_awaitable(value: Any) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        close()


def format_token(token: Any) -> str:
    if inspect.isclass(token):
        module = getattr(token, "__module__", "")
        name = getattr(token, "__qualname__", token.__name__)
        if module and module != "builtins":
            return f"{module}.{name}"
        return name
    name = getattr(token, "__qualname__", None) or getattr(token, "__name__", None)
    return str(name) if name else repr(token)
