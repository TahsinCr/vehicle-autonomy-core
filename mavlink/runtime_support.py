"""Narrow internal coordination boundary shared by MAVLink runtimes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from .actions import MavlinkAction

if TYPE_CHECKING:
    from ..events import Subscription
    from .filter import MessagePredicate, MessageTypeInput, MavlinkMessageFilter
    from .runtime import MavlinkRuntime


class MavlinkRuntimeSupport:
    """Expose async coordination without leaking runtime-owned components."""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: "MavlinkRuntime") -> None:
        self._runtime = runtime

    def configure_async_io(
        self,
        operation: Callable[[Callable[[], Any]], Awaitable[Any]],
    ) -> None:
        self._runtime._registry.async_io = operation

    def fail_waiters(self) -> None:
        self._runtime._registry.fail_waiters()

    def subscribe(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        callback: Callable[[Any], Any],
        *,
        predicate: MessagePredicate | None = None,
        once: bool = False,
        **options: Any,
    ) -> Subscription:
        return self._runtime._subscribe(
            message_types,
            callback,
            predicate=predicate,
            once=once,
            **options,
        )

    def has_pending_handlers(self) -> bool:
        return bool(self._runtime._application_handlers._tasks)

    async def finish_handlers(self) -> None:
        await self._runtime._application_handlers.finish_async()

    async def emit_action(self, name: str, source: Any) -> None:
        await self._runtime._emit_async(f"action:{name}", MavlinkAction(source))

    async def emit_error(self, error: Exception, source: Any) -> None:
        await self._runtime._emit_async(
            "action:error",
            MavlinkAction(source, error=error),
        )
