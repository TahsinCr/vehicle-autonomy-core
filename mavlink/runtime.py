"""High-level MAVLink runtime that composes the reusable low-level pieces."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from ..abstracts import Service
from ..compatibility import ExceptionGroup
from ..events import EventBus, Subscription
from .application import MavlinkApplicationChannel, MavlinkApplicationPacket
from .client import MavlinkClient
from .dispatch import (
    MavlinkApplicationDispatcher,
    MavlinkApplicationHandler,
)
from .endpoint import MavlinkEndpoint
from .history import MessageHistory
from .delivery import CallbackWorker
from .filter import MessagePredicate, MessageTypeInput, MavlinkMessageFilter
from .peer import MavlinkApplicationPeer, MavlinkApplicationResponse
from .router import MavlinkIngressFilter, MavlinkRouterStats
from .actions import MavlinkAction, MavlinkActions
from .vehicles import VehicleRegistry
from .handlers import ApplicationHandlers


@dataclass(frozen=True, slots=True)
class MavlinkRuntimeError:
    source: str
    error: Exception


@dataclass(frozen=True, slots=True)
class MavlinkRuntimeState:
    running: bool
    connected: bool
    application_enabled: bool
    peer_alive: bool
    router: MavlinkRouterStats


class MavlinkRuntime(MavlinkActions, Service):
    """Offer one lifecycle and a small API for telemetry and application data."""

    action_names = frozenset({"start", "stop", "error"})

    def __init__(
        self,
        endpoint: MavlinkEndpoint | None = None,
        *,
        client: MavlinkClient | None = None,
        router_options: Mapping[str, Any] | None = None,
        application_role: str | None = None,
        channel: MavlinkApplicationChannel | None = None,
        peer: MavlinkApplicationPeer | None = None,
        dispatcher: MavlinkApplicationDispatcher | None = None,
        workers: int = 1,
        max_pending: int = 64,
        channel_options: Mapping[str, Any] | None = None,
        peer_options: Mapping[str, Any] | None = None,
        heartbeat_timeout: float = 5.0,
        vehicle_history: int = 128,
        vehicle_state_retention: float | None = None,
        _delivery=None,
        callback_capacity: int = 1024,
        callback_action_capacity: int = 1024,
    ) -> None:
        MavlinkActions.__init__(self, _delivery)
        self._worker = CallbackWorker(callback_capacity, callback_action_capacity) if _delivery is None else None
        if client is not None and endpoint is not None and client.endpoint != endpoint:
            raise ValueError("MAVLink runtime endpoint and client endpoint do not match")
        if client is not None and router_options:
            raise ValueError("router_options cannot be used with a custom client")
        self.client = client or MavlinkClient(
            endpoint or MavlinkEndpoint(),
            router_options=router_options,
        )
        self.connection = self.client.connection
        self.router = self.client.router

        role = str(application_role).strip().lower() if application_role else ""
        if channel is not None and peer is None and not role:
            raise ValueError("A custom application channel requires a role or peer")
        if dispatcher is not None and peer is None:
            raise ValueError("A custom dispatcher requires an application peer")

        if peer is None and role:
            channel = channel or MavlinkApplicationChannel(
                self.client,
                **dict(channel_options or {}),
            )
            peer = MavlinkApplicationPeer(
                channel,
                role=role,
                target_system=lambda: self.connection.target_system,
                target_component=lambda: self.connection.target_component,
                transport_available=lambda: self.client.is_connected,
                **dict(peer_options or {}),
            )
        self.channel = channel
        self.peer = peer
        self.dispatcher = dispatcher or (
            MavlinkApplicationDispatcher(
                peer,
                workers=workers,
                max_pending=max_pending,
            )
            if peer is not None
            else None
        )

        self.errors = EventBus[MavlinkRuntimeError](history=100)
        self._error_subscriptions: list[Subscription] = []
        self._histories: dict[MessageHistory, Subscription] = {}
        self._ingress_filters: dict[int, Subscription] = {}
        self._running = False
        self._cleanup_pending = False
        self._closed = False
        self._closing = False
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_owner: int | None = None
        self._close_condition = threading.Condition(self._lock)
        self._close_owner = None
        self._close_error = None
        self._registry = VehicleRegistry(
            self, delivery=_delivery, heartbeat_timeout=heartbeat_timeout,
            history_capacity=vehicle_history,
            state_retention=vehicle_state_retention,
        )
        self.vehicles = self._registry.vehicles
        self._application_handlers = ApplicationHandlers(self)
        if self._worker is not None:
            self._worker.on_failure = self._worker_failed
        self._bridge_errors()

    def _worker_failed(self, error: Exception) -> None:
        with self._registry.condition:
            self._registry.condition.notify_all()
        if not self.errors.closed:
            self.errors.publish(MavlinkRuntimeError("callbacks", error))
            self._emit_sync("action:error", MavlinkAction(self, error=error))

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running and (self._worker is None or self._worker.failure is None)

    @property
    def delivery_error(self) -> Exception | None:
        return self._worker.failure if self._worker is not None else self._delivery.failure

    def _check_delivery(self) -> None:
        if self._worker is not None:
            self._worker.raise_if_failed()
        elif self._delivery is not None:
            self._delivery.raise_if_failed()

    @property
    def dropped_callbacks(self) -> int:
        return self._worker.dropped if self._worker is not None else self._delivery.dropped

    def prune_vehicles(self, *, older_than: float | None = None) -> int:
        """Remove disconnected vehicle/component state eligible for retention cleanup."""

        return self._registry.prune(older_than=older_than)

    def add_history(self, history: MessageHistory) -> Subscription:
        """Record future envelopes until cancelled; storage remains caller-owned."""

        if not isinstance(history, MessageHistory):
            raise TypeError("history must be a MessageHistory instance")
        with self._lock:
            if self._closed or self._closing:
                raise RuntimeError("Runtime is closed")
            history._check_open()
            if history in self._histories:
                raise ValueError("History is already attached")
            failed = False
            attachment: dict[str, Subscription] = {}

            def record(envelope: MavlinkMessageEnvelope) -> None:
                nonlocal failed
                if failed:
                    return
                try:
                    history.append(envelope)
                except Exception as error:
                    failed = True
                    try:
                        self._publish_error("history", error)
                    finally:
                        attached = attachment.get("subscription")
                        if attached is not None:
                            attached.cancel()

            source = self.router.envelopes.subscribe(record)

            def cancel() -> None:
                with self._lock:
                    source.cancel()
                    self._histories.pop(history, None)

            subscription = Subscription(source.id, cancel)
            attachment["subscription"] = subscription
            self._histories[history] = subscription
            if failed:
                subscription.cancel()
            return subscription

    def add_filter(self, predicate: MavlinkIngressFilter) -> Subscription:
        """Reject unwanted traffic before runtime state and discovery update."""

        with self._lock:
            if self._closed or self._closing:
                raise RuntimeError("Runtime is closed")
            source = self.router.add_filter(predicate)

            def cancel() -> None:
                source.cancel()
                with self._lock:
                    self._ingress_filters.pop(source.id, None)

            subscription = Subscription(source.id, cancel)
            self._ingress_filters[source.id] = subscription
            return subscription

    @property
    def application_enabled(self) -> bool:
        return self.peer is not None and self.dispatcher is not None

    @property
    def messages(self) -> EventBus[Any]:
        return self.router.messages

    @property
    def packets(self) -> EventBus[MavlinkApplicationPacket]:
        if self.peer is None:
            raise RuntimeError("MAVLink application channel is not configured")
        return self.peer.packets

    @property
    def state(self) -> MavlinkRuntimeState:
        return MavlinkRuntimeState(
            running=self.running,
            connected=self.client.is_connected,
            application_enabled=self.application_enabled,
            peer_alive=bool(self.peer is not None and self.peer.alive),
            router=self.router.stats,
        )

    @contextmanager
    def _lifecycle_operation(self) -> Iterator[None]:
        # Never wait from a thread that a lifecycle operation may be joining.
        current = threading.current_thread()
        identifier = threading.get_ident()
        if self._lifecycle_owner == identifier:
            raise RuntimeError("A MAVLink lifecycle operation is already active on this thread")
        owned = (current is getattr(self.router, "_thread", None)
                 or current is self._registry._monitor
                 or (self._worker is not None and current is self._worker._thread))
        if not self._lifecycle_lock.acquire(blocking=not owned):
            raise RuntimeError("Another MAVLink lifecycle operation is in progress")
        self._lifecycle_owner = identifier
        try:
            yield
        finally:
            self._lifecycle_owner = None
            self._lifecycle_lock.release()

    def start(self) -> None:
        with self._lifecycle_operation():
            self._start()

    def _start(self) -> None:
        """Start transport, application peer, and dispatcher in safe order."""

        with self._lock:
            if self._closed or self._closing:
                raise RuntimeError("MAVLink runtime is closed")
            if self._cleanup_pending:
                raise RuntimeError("MAVLink runtime cleanup must complete before restart")
            if self._running:
                self._check_delivery()
                return
        started: list[Service | VehicleRegistry | ApplicationHandlers] = []
        try:
            if self._worker is not None:
                self._worker.start()
                started.append(self._worker)
            self.client.start()
            started.append(self.client)
            if self.peer is not None:
                self.peer.start()
                started.append(self.peer)
            elif self.channel is not None:
                self.channel.start()
                started.append(self.channel)
            if self.dispatcher is not None:
                self._application_handlers.start()
                started.append(self._application_handlers)
                self.dispatcher.start()
                started.append(self.dispatcher)
            with self._lock:
                self._running = True
            self._registry.start()
            started.append(self._registry)
        except Exception as exc:
            self._publish_error("start", exc)
            cleanup_failed = False
            for service in reversed(started):
                try:
                    service.stop()
                except Exception as stop_error:
                    cleanup_failed = True
                    self._publish_error("rollback", stop_error)
            with self._lock:
                self._cleanup_pending = cleanup_failed
                self._running = False
            raise
        if self._delivery is None:
            self._emit("action:start", MavlinkAction(self))
        heartbeat = getattr(self.connection, "initial_heartbeat", None)
        if heartbeat is not None:
            from .message import MavlinkMessageEnvelope
            self._registry.accept(MavlinkMessageEnvelope.wrap(0, heartbeat))

    def stop(self) -> None:
        with self._lifecycle_operation():
            self._stop()

    def _stop(self) -> None:
        """Stop every owned layer in reverse order and preserve all errors."""

        with self._lock:
            if not self._running and not self._cleanup_pending:
                return
            self._running = False
            self._cleanup_pending = True
        services: list[Service | VehicleRegistry | ApplicationHandlers] = [
            self._registry, self._application_handlers,
        ]
        if self.dispatcher is not None:
            services.append(self.dispatcher)
        if self.peer is not None:
            services.append(self.peer)
        elif self.channel is not None:
            services.append(self.channel)
        services.append(self.client)
        if self._worker is not None:
            services.append(self._worker)

        errors: list[Exception] = []
        for service in services:
            try:
                service.stop()
            except Exception as exc:
                errors.append(exc)
                self._publish_error("stop", exc)
        if errors:
            raise ExceptionGroup("MAVLink runtime shutdown failed", errors)
        with self._lock:
            self._cleanup_pending = False
        if self._delivery is None:
            self._emit("action:stop", MavlinkAction(self))

    def close(self) -> None:
        """Stop owned services and permanently release runtime subscriptions."""

        with self._lock:
            if self._closing:
                current = threading.current_thread()
                if (self._close_owner == threading.get_ident()
                        or current is getattr(self.router, "_thread", None)
                        or current is self._registry._monitor
                        or (self._worker is not None and current is self._worker._thread)):
                    return
                self._close_condition.wait_for(lambda: not self._closing)
                if self._close_error is not None:
                    raise self._close_error
            if self._closed:
                return
            self._closing = True
            self._close_owner = threading.get_ident()
            self._close_error = None
        try:
            self.stop()
            self._registry.close()
            self._application_handlers.close()
            for subscription in tuple(self._histories.values()):
                subscription.cancel()
            for subscription in tuple(self._ingress_filters.values()):
                subscription.cancel()
            with self._lock:
                self._closed = True
                subscriptions = tuple(self._error_subscriptions)
                self._error_subscriptions.clear()
            for subscription in subscriptions:
                subscription.cancel()
            self.errors.close()
            self._close_actions()
        except BaseException as exc:
            with self._lock:
                self._close_error = exc
            raise
        finally:
            with self._lock:
                self._closing = False
                self._close_owner = None
                self._close_condition.notify_all()

    def reconnect(self) -> None:
        self.stop()
        self.start()

    def subscribe(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        callback: Callable[[Any], None] | None = None,
        *,
        predicate: MessagePredicate | None = None,
        once: bool = False,
        **options,
    ) -> Subscription:
        if callback is None:
            return lambda function: self.subscribe(message_types, function, predicate=predicate, once=once, **options)
        message_filter = (
            message_types
            if isinstance(message_types, MavlinkMessageFilter)
            else MavlinkMessageFilter(
                message_types=message_types,
            )
        )
        if isinstance(message_types, MavlinkMessageFilter) and predicate is not None:
            raise ValueError("Use a MavlinkMessageFilter or predicate, not both")
        from dataclasses import replace
        execution_predicate = predicate or message_filter.predicate
        message_filter = replace(message_filter, predicate=None)
        topic = f"raw:{next(self._ids)}"
        registration = self._register(topic, callback, once=once, predicate=execution_predicate, **options)
        try:
            source = self.client.subscribe(lambda message: self._emit(topic, message), message_filter)
        except BaseException:
            registration.cancel()
            raise
        original_cancel = registration._cancel
        def cancel() -> None:
            original_cancel()
            source.cancel()
        registration._cancel = cancel
        if not registration.active:
            source.cancel()
        return registration

    def on_start(self, callback=None, *, once=False, **options):
        return self.on("start", callback, once=once, **options)

    def on_stop(self, callback=None, *, once=False, **options):
        return self.on("stop", callback, once=once, **options)

    def once(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        callback: Callable[[Any], None] | None = None,
        *,
        predicate: MessagePredicate | None = None,
    ) -> Subscription:
        """Handle the first matching MAVLink message and then unsubscribe."""

        return self.subscribe(message_types, callback, predicate=predicate, once=True)

    def wait_for(
        self,
        message_types: MavlinkMessageFilter | MessageTypeInput,
        *,
        predicate: MessagePredicate | None = None,
        timeout: float = 3.0,
        after_sequence: int | None = None,
    ) -> Any:
        self._check_delivery()
        result = self.client.wait_for(
            message_types,
            predicate=predicate,
            timeout=timeout,
            after_sequence=after_sequence,
        )
        self._check_delivery()
        return result

    def latest(
        self,
        message_filter: MavlinkMessageFilter | MessageTypeInput | None = None,
    ) -> Any | None:
        return self.client.latest(message_filter)

    def send(self, message: Any) -> None:
        self._check_delivery()
        self.client.send(message)

    def send_named(self, message_name: str, **parameters: Any) -> None:
        self._check_delivery()
        self.client.send_named(message_name, **parameters)

    def handle(
        self,
        packet_type: str,
        handler: MavlinkApplicationHandler | None = None,
        *,
        replace: bool = False,
    ) -> Subscription:
        return self._application_handlers.register(packet_type, handler, replace=replace)

    def notify(
        self,
        packet_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> MavlinkApplicationPacket:
        self._check_delivery()
        if self.peer is None:
            raise RuntimeError("MAVLink application peer is not configured")
        return self.peer.send(packet_type, payload)

    def request(
        self,
        packet_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        response_types: str | tuple[str, ...] | frozenset[str] = (
            "system.ack",
            "system.error",
        ),
        timeout: float = 3.0,
    ) -> MavlinkApplicationResponse:
        self._check_delivery()
        if self.peer is None:
            raise RuntimeError("MAVLink application peer is not configured")
        return self.peer.request(
            packet_type,
            payload,
            response_types=response_types,
            timeout=timeout,
        )

    def _bridge_errors(self) -> None:
        sources = (
            ("connection", getattr(self.connection, "errors", None)),
            ("router", getattr(self.router, "errors", None)),
            ("channel", getattr(self.channel, "errors", None)),
            ("peer", getattr(self.peer, "errors", None)),
            ("dispatcher", getattr(self.dispatcher, "errors", None)),
        )
        for name, events in sources:
            if events is None:
                continue
            self._error_subscriptions.append(
                events.subscribe(lambda error, source=name: self._publish_error(source, error))
            )

    def _publish_error(self, source: str, error: Any) -> None:
        if not isinstance(error, Exception):
            error = getattr(error, "error", RuntimeError(str(error)))
        if not self.errors.closed:
            self.errors.publish(MavlinkRuntimeError(source, error))
            self._emit("action:error", MavlinkAction(self, error=error))
            self._registry.report_error(error)

    def __enter__(self) -> "MavlinkRuntime":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
