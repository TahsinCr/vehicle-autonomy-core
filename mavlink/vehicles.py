"""Discovered vehicles and components sharing one transport and reader."""

from __future__ import annotations

import asyncio
import copy
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from .actions import MavlinkAction, MavlinkActions
from .message import MavlinkMessageEnvelope


@dataclass(frozen=True, slots=True)
class MavlinkVehicleState:
    connected: bool
    last_seen_monotonic: float | None


class MavlinkCollection(MavlinkActions):
    """Snapshot iteration and lookup never create a remote endpoint."""

    action_names = MavlinkActions.action_names | {"added", "removed"}

    def __init__(self, registry, owner=None):
        super().__init__(registry.delivery)
        self._worker = getattr(registry.runtime, "_worker", None)
        self._registry = registry
        self._owner = owner
        self._items: dict[int, Any] = {}

    def __iter__(self):
        with self._registry.condition:
            return iter(tuple(self._items.values()))

    def __len__(self):
        with self._registry.condition:
            return len(self._items)

    def get(self, identifier: int):
        with self._registry.condition:
            return self._items.get(identifier)

    def get_component(self, component_id: int):
        """Return a snapshot of matching components across discovered vehicles."""
        if self._owner is not None:
            raise TypeError("Use vehicle.get_component(id) within a vehicle")
        if isinstance(component_id, bool) or not isinstance(component_id, int) or not 1 <= component_id <= 255:
            raise ValueError("Component ID must be an integer from 1 to 255")
        with self._registry.condition:
            return tuple(
                component for vehicle in self._items.values()
                if (component := vehicle._components._items.get(component_id)) is not None
            )

    def on_added(self, callback=None, *, once=False, **options):
        return self.on("added", callback, once=once, **options)

    def on_removed(self, callback=None, *, once=False, **options):
        return self.on("removed", callback, once=once, **options)

    def _available(self):
        return next((item for item in self._items.values() if item._connected), None)

    def wait_for(self, *, timeout: float | None = None):
        if self._worker is not None:
            self._worker.raise_if_failed()
        _validate_timeout(timeout)
        with self._registry.condition:
            self._registry.condition.wait_for(
                lambda: self._available() is not None or not self._registry.running
                or self._actions_closed or (self._worker is not None and self._worker.failure is not None),
                timeout,
            )
            if self._worker is not None:
                self._worker.raise_if_failed()
            return self._available() if self._registry.running else None

    def remove(self, identifier: int) -> bool:
        return self._registry.remove(self, identifier)


class AsyncMavlinkCollection(MavlinkCollection):
    async def wait_for(self, *, timeout: float | None = None):
        self._registry.delivery.raise_if_failed()
        _validate_timeout(timeout)
        with self._registry.condition:
            if not self._registry.running or self._actions_closed:
                return None
        loop = asyncio.get_running_loop()
        if self._registry.delivery._loop is not loop:
            raise RuntimeError("Start the async runtime on this loop before waiting")
        future = loop.create_future()
        with self._registry.condition:
            available = self._available()
            if available is not None or not self._registry.running:
                return available if self._registry.running else None
            self._registry.waiters[future] = self
        try:
            result = await asyncio.wait_for(future, timeout)
            self._registry.delivery.raise_if_failed()
            return result
        except asyncio.TimeoutError:
            return None
        finally:
            with self._registry.condition:
                self._registry.waiters.pop(future, None)


def _validate_timeout(timeout):
    if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
        raise ValueError("Timeout must be nonnegative and finite")


class _MavlinkNode(MavlinkActions):
    def __init__(self, registry, vehicle, component_id):
        super().__init__(registry.delivery)
        self._registry = registry
        self._vehicle = vehicle
        self._system_id = vehicle.system_id
        self._component_id = component_id
        self._is_autopilot = False
        self._connected = False
        self._last_seen = None
        self._history = deque(maxlen=registry.history_capacity)
        self._worker = getattr(registry.runtime, "_worker", None)
        self._latest = {}

    @property
    def vehicle(self):
        return self._vehicle

    @property
    def system_id(self) -> int:
        return self._system_id

    @property
    def component_id(self) -> int | None:
        return self._component_id

    @property
    def state(self):
        with self._registry.condition:
            return MavlinkVehicleState(self._connected, self._last_seen)

    def latest(self, message_type: str):
        normalized = message_type.strip().upper()
        with self._registry.condition:
            return self._latest.get(normalized)

    def history(self, message_type: str | None = None):
        with self._registry.condition:
            result = tuple(self._history)
        if message_type is None:
            return result
        normalized = message_type.strip().upper()
        return tuple(item for item in result if item.message_type == normalized)

    def _target(self):
        if self._worker is not None:
            self._worker.raise_if_failed()
        with self._registry.condition:
            if not self._registry.running or not self._connected or self._actions_closed:
                raise RuntimeError("MAVLink endpoint is unavailable")
            if self._delivery is not None:
                self._delivery.raise_if_failed()
            if self.vehicle is self:
                target = self._components._items.get(self.component_id)
                if target is None or not target._connected:
                    raise RuntimeError("No live autopilot component has been discovered")
            return self.component_id

    def send_named(self, message_name: str, **parameters):
        target = self._target()
        if "target_system" in parameters or "target_component" in parameters:
            raise ValueError("Target is owned by the vehicle/component scope")
        self._registry.runtime.connection.send_named(
            message_name, target_system=self.system_id,
            target_component=target, **parameters,
        )

    def send(self, message):
        """Send a detached targeted message without changing caller-owned data."""
        target = self._target()
        if not hasattr(message, "target_system") or not hasattr(message, "target_component"):
            raise ValueError("Scoped sending requires a message with target fields")
        outgoing = copy.copy(message)
        outgoing.target_system = self.system_id
        outgoing.target_component = target
        self._registry.runtime.connection.send(outgoing)

    def request_message_rate(self, message_id: int | str, frequency_hz: float):
        target = self._target()
        connection = self._registry.runtime.connection
        if isinstance(message_id, str):
            name = f"MAVLINK_MSG_ID_{message_id.strip().upper()}"
            try:
                message_id = getattr(connection.mavlink, name)
            except AttributeError as exc:
                raise ValueError(f"Unknown MAVLink message: {message_id}") from exc
        return connection.request_message_rate(
            message_id, frequency_hz,
            target_system=self.system_id, target_component=target,
        )

    def notify(self, packet_type, payload=None):
        target = self._target()
        peer = self._registry.runtime.peer
        if peer is None:
            raise RuntimeError("Application channel is not configured")
        return peer.send(packet_type, payload, target_system=self.system_id,
                         target_component=target)

    def request(self, packet_type, payload=None, *, timeout=3.0,
                response_types=("system.ack", "system.error")):
        target = self._target()
        peer = self._registry.runtime.peer
        if peer is None:
            raise RuntimeError("Application channel is not configured")
        return peer.request(packet_type, payload, timeout=timeout,
                            response_types=response_types,
                            target_system=self.system_id, target_component=target)

    def handle(self, packet_type, handler=None, *, replace=False):
        return self._registry.runtime._application_handlers.register(
            packet_type, handler, scope=self, replace=replace,
        )

    def _message_after(self, message_type, boundary):
        return next((item for item in self._history
                     if item.received_monotonic >= boundary
                     and item.message_type == message_type), None)

    def wait_for(self, message_type: str, *, timeout: float | None = None):
        """Wait for a new matching message; return None on timeout or shutdown."""
        if self._worker is not None:
            self._worker.raise_if_failed()
        _validate_timeout(timeout)
        normalized = message_type.strip().upper()
        if not normalized:
            raise ValueError("Message type must not be empty")
        with self._registry.condition:
            boundary = time.monotonic()
            self._registry.condition.wait_for(
                lambda: self._message_after(normalized, boundary) is not None
                or not self._registry.running or self._actions_closed
                or (self._worker is not None and self._worker.failure is not None), timeout,
            )
            if self._worker is not None:
                self._worker.raise_if_failed()
            return self._message_after(normalized, boundary) if self._registry.running else None


class MavlinkComponent(_MavlinkNode):
    """One discovered component with source-scoped telemetry and sending."""


class MavlinkVehicle(_MavlinkNode):
    def __init__(self, registry, system_id):
        self._system_id = system_id
        super().__init__(registry, self, None)
        self._components = registry.collection_type(registry, self)

    def get_component(self, component_id: int):
        """Return a discovered component, or None when it is unknown."""
        return self._components.get(component_id)

    def get_components(self):
        """Return a snapshot of this vehicle's discovered components."""
        return tuple(self._components)

    def wait_for_component(self, *, timeout=None):
        """Wait for a connected component; return None on timeout or stop."""
        return self._components.wait_for(timeout=timeout)

    def remove_component(self, component_id: int):
        return self._components.remove(component_id)

    def on_component_added(self, callback=None, *, once=False, **options):
        return self._components.on_added(callback, once=once, **options)

    def on_component_removed(self, callback=None, *, once=False, **options):
        return self._components.on_removed(callback, once=once, **options)

    def on_component_connected(self, callback=None, *, once=False, **options):
        return self._components.on_connected(callback, once=once, **options)

    def on_component_disconnected(self, callback=None, *, once=False, **options):
        return self._components.on_disconnected(callback, once=once, **options)

class _AsyncMavlinkNode(_MavlinkNode):
    async def send(self, message):
        return await asyncio.to_thread(_MavlinkNode.send, self, message)

    async def wait_for(self, message_type: str, *, timeout: float | None = None):
        self._registry.delivery.raise_if_failed()
        _validate_timeout(timeout)
        normalized = message_type.strip().upper()
        if not normalized:
            raise ValueError("Message type must not be empty")
        with self._registry.condition:
            if not self._registry.running or self._actions_closed:
                return None
        loop = asyncio.get_running_loop()
        if self._registry.delivery._loop is not loop:
            raise RuntimeError("Start the async runtime on this loop before waiting")
        future = loop.create_future()
        with self._registry.condition:
            if not self._registry.running or self._actions_closed:
                return None
            boundary = time.monotonic()
            self._registry.message_waiters[future] = (self, normalized, boundary)
        try:
            result = await asyncio.wait_for(future, timeout)
            self._registry.delivery.raise_if_failed()
            return result
        except asyncio.TimeoutError:
            return None
        finally:
            with self._registry.condition:
                self._registry.message_waiters.pop(future, None)

    async def send_named(self, message_name, **parameters):
        return await asyncio.to_thread(_MavlinkNode.send_named, self,
                                       message_name, **parameters)

    async def request_message_rate(self, message_id, frequency_hz):
        return await asyncio.to_thread(_MavlinkNode.request_message_rate,
                                       self, message_id, frequency_hz)

    async def notify(self, packet_type, payload=None):
        return await asyncio.to_thread(_MavlinkNode.notify, self, packet_type, payload)

    async def request(self, packet_type, payload=None, **options):
        return await asyncio.to_thread(_MavlinkNode.request, self,
                                       packet_type, payload, **options)


class AsyncMavlinkComponent(_AsyncMavlinkNode):
    """One discovered component with awaitable transport operations."""


class AsyncMavlinkVehicle(_AsyncMavlinkNode, MavlinkVehicle):
    """Same discovered endpoint, with awaitable transport operations."""

    async def wait_for_component(self, *, timeout=None):
        return await self._components.wait_for(timeout=timeout)


class VehicleRegistry:
    """Source-indexed routing; a single monitor serves every discovered endpoint."""

    def __init__(self, runtime, *, delivery=None, heartbeat_timeout=5.0,
                 history_capacity=128):
        if not math.isfinite(heartbeat_timeout) or heartbeat_timeout <= 0:
            raise ValueError("Heartbeat timeout must be positive and finite")
        if isinstance(history_capacity, bool) or not isinstance(history_capacity, int) or history_capacity <= 0:
            raise ValueError("History capacity must be a positive integer")
        self.runtime = runtime
        self.delivery = delivery
        self.timeout = heartbeat_timeout
        self.history_capacity = history_capacity
        self.condition = threading.Condition(threading.RLock())
        self.collection_type = AsyncMavlinkCollection if delivery else MavlinkCollection
        self.vehicle_type = AsyncMavlinkVehicle if delivery else MavlinkVehicle
        self.component_type = AsyncMavlinkComponent if delivery else MavlinkComponent
        self.vehicles = self.collection_type(self)
        self.running = False
        self.waiters = {}
        self.message_waiters = {}
        self._stop = threading.Event()
        self._monitor = None
        self._subscription = None

    def start(self):
        with self.condition:
            if self.running:
                return
            if self._monitor is not None and self._monitor.is_alive():
                raise RuntimeError("Previous vehicle monitor has not stopped")
            self.running = True
            self._stop.clear()
            self._subscription = self.runtime.router.envelopes.subscribe(self.accept)
            self._monitor = threading.Thread(target=self._monitor_loop,
                                             name="mavlink-vehicles", daemon=True)
            self._monitor.start()

    def _wake_waiters_locked(self):
        self.condition.notify_all()
        for future, collection in tuple(self.waiters.items()):
            available = collection._available() if self.running else None
            if available is not None or not self.running or collection._actions_closed:
                self.waiters.pop(future, None)
                def finish(future=future, available=available):
                    if not future.done():
                        future.set_result(available)
                try:
                    future.get_loop().call_soon_threadsafe(finish)
                except RuntimeError:
                    pass

        for future, (endpoint, message_type, boundary) in tuple(self.message_waiters.items()):
            available = endpoint._message_after(message_type, boundary) if self.running else None
            if available is not None or not self.running or endpoint._actions_closed:
                self.message_waiters.pop(future, None)
                def finish(future=future, available=available):
                    if not future.done():
                        future.set_result(available)
                try:
                    future.get_loop().call_soon_threadsafe(finish)
                except RuntimeError:
                    pass

    def fail_waiters(self):
        """Wake pending async waits on the owning loop to observe the fault."""
        with self.condition:
            futures = (*self.waiters, *self.message_waiters)
            self.waiters.clear()
            self.message_waiters.clear()
        for future in futures:
            if not future.done():
                future.set_result(None)

    def accept(self, envelope: MavlinkMessageEnvelope):
        system, component_id = envelope.source_system, envelope.source_component
        if system is None or component_id is None or not 1 <= system <= 255 or not 1 <= component_id <= 255:
            return
        actions = []
        with self.condition:
            if not self.running:
                return
            vehicle = self.vehicles._items.get(system)
            if vehicle is None:
                # Only autopilot heartbeats establish a vehicle identity. This
                # excludes GCS/companion systems from the vehicle collection.
                message = envelope.message
                if envelope.message_type != "HEARTBEAT":
                    return
                dialect = self.runtime.connection.mavlink
                if (getattr(message, "autopilot", dialect.MAV_AUTOPILOT_INVALID)
                        == dialect.MAV_AUTOPILOT_INVALID
                        or getattr(message, "type", None) == dialect.MAV_TYPE_GCS):
                    return
                vehicle = self.vehicle_type(self, system)
                self.vehicles._items[system] = vehicle
                actions.append((self.vehicles, "added", vehicle, None))
            component = vehicle._components._items.get(component_id)
            if component is None:
                component = self.component_type(self, vehicle, component_id)
                vehicle._components._items[component_id] = component
                actions.append((vehicle._components, "added", vehicle, component))
            if envelope.message_type == "HEARTBEAT":
                dialect = self.runtime.connection.mavlink
                component._is_autopilot = (
                    getattr(envelope.message, "autopilot", dialect.MAV_AUTOPILOT_INVALID)
                    != dialect.MAV_AUTOPILOT_INVALID
                    and getattr(envelope.message, "type", None) != dialect.MAV_TYPE_GCS
                )
                for endpoint, collection in ((vehicle, self.vehicles), (component, vehicle._components)):
                    if not endpoint._connected:
                        actions.append((endpoint, "connected", vehicle, component if endpoint is component else None))
                        actions.append((collection, "connected", vehicle, component if endpoint is component else None))
                    endpoint._connected = True
                    endpoint._last_seen = envelope.received_monotonic
                self._select_autopilot_locked(vehicle)
            vehicle._history.append(envelope)
            component._history.append(envelope)
            vehicle._latest[envelope.message_type] = envelope
            component._latest[envelope.message_type] = envelope
            self._wake_waiters_locked()
        for scope, name, owner, member in actions:
            if not self.running or scope._actions_closed:
                break
            scope._emit(f"action:{name}", MavlinkAction(scope, owner, member))
        for scope in (self.vehicles, vehicle, vehicle._components, component):
            if not self.running or scope._actions_closed:
                break
            scope._emit(f"message:{envelope.message_type}", envelope)

    def expire(self, now=None):
        now = time.monotonic() if now is None else now
        actions = []
        with self.condition:
            if not self.running:
                return
            for vehicle in self.vehicles._items.values():
                for endpoint, collection in ((vehicle, self.vehicles), *(
                    (component, vehicle._components) for component in vehicle._components._items.values()
                )):
                    if endpoint._connected and now - endpoint._last_seen >= self.timeout:
                        endpoint._connected = False
                        component = None if endpoint is vehicle else endpoint
                        actions.extend((scope, vehicle, component) for scope in (endpoint, collection))
                self._select_autopilot_locked(vehicle)
        for scope, vehicle, component in actions:
            scope._emit("action:disconnected", MavlinkAction(scope, vehicle, component))

    def _monitor_loop(self):
        while not self._stop.wait(min(self.timeout / 2, 1.0)):
            self.expire()

    def _select_autopilot_locked(self, vehicle):
        current = vehicle._components._items.get(vehicle.component_id)
        if current is not None and current._connected and current._is_autopilot:
            return
        vehicle._component_id = min(
            (item.component_id for item in vehicle._components._items.values()
             if item._connected and item._is_autopilot), default=None,
        )

    def remove(self, collection, identifier):
        with self.condition:
            endpoint = collection._items.get(identifier)
            if endpoint is None:
                return False
            if endpoint._connected:
                raise RuntimeError("Disconnect an endpoint before removing it")
            if endpoint.vehicle is endpoint and any(c._connected for c in endpoint._components._items.values()):
                raise RuntimeError("Vehicle still has live components")
            collection._items.pop(identifier)
            if collection._owner is not None:
                self._select_autopilot_locked(collection._owner)
            self._wake_waiters_locked()
        self._close_endpoint(endpoint)
        with self.condition:
            self._wake_waiters_locked()
        collection._emit("action:removed", MavlinkAction(collection, endpoint.vehicle,
                         None if endpoint.vehicle is endpoint else endpoint))
        return True

    def report_error(self, error):
        for vehicle in self.vehicles:
            self.vehicles._emit("action:error", MavlinkAction(self.vehicles, vehicle, error=error))
            vehicle._emit("action:error", MavlinkAction(vehicle, vehicle, error=error))
            for component in vehicle._components:
                event = MavlinkAction(component, vehicle, component, error)
                vehicle._components._emit("action:error", event)
                component._emit("action:error", event)

    def _close_endpoint(self, endpoint):
        if endpoint.vehicle is endpoint:
            for component in endpoint._components:
                self.runtime._application_handlers.remove_scope(component)
                component._close_actions()
            endpoint._components._close_actions()
        self.runtime._application_handlers.remove_scope(endpoint)
        endpoint._close_actions()

    def stop(self):
        with self.condition:
            self.running = False
            self._stop.set()
            subscription, self._subscription = self._subscription, None
            monitor = self._monitor
            self._wake_waiters_locked()
        if subscription:
            subscription.cancel()
        if monitor and monitor is not threading.current_thread():
            monitor.join(2.0)
            if monitor.is_alive():
                raise TimeoutError("Vehicle monitor has not stopped")
        with self.condition:
            actions = []
            for vehicle in self.vehicles._items.values():
                for endpoint, collection in ((vehicle, self.vehicles), *(
                    (component, vehicle._components) for component in vehicle._components._items.values()
                )):
                    if endpoint._connected:
                        endpoint._connected = False
                        member = None if endpoint is vehicle else endpoint
                        actions.extend((scope, vehicle, member) for scope in (endpoint, collection))
        for scope, vehicle, component in actions:
            scope._emit("action:disconnected", MavlinkAction(scope, vehicle, component))

    def close(self):
        self.stop()
        for vehicle in self.vehicles:
            self._close_endpoint(vehicle)
        self.vehicles._close_actions()
