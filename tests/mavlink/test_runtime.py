from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from src.core.events import EventBus
from src.core.compatibility import ExceptionGroup
from src.core.mavlink import (
    AsyncMavlinkRuntime,
    MavlinkMessageEnvelope,
    MavlinkApplicationPacket,
    MavlinkEndpoint,
    MavlinkRuntime,
    MavlinkRouterStats,
)
import asyncio
import threading


class FakeConnection:
    def __init__(self) -> None:
        self.errors = EventBus[Exception]()
        self.target_system = 1
        self.target_component = 1
        self.mavlink = SimpleNamespace(MAV_AUTOPILOT_INVALID=8, MAV_TYPE_GCS=6,
                                       MAVLINK_MSG_ID_HEARTBEAT=0)


class FakeRouter:
    def __init__(self) -> None:
        self.messages = EventBus[Any]()
        self.envelopes = EventBus[Any]()
        self.errors = EventBus[Any]()

    @property
    def stats(self) -> MavlinkRouterStats:
        return MavlinkRouterStats(False, 0, 0, 0, 0, 0, None, None, None)


class FakeClient:
    def __init__(self, calls: list[str]) -> None:
        self.endpoint = MavlinkEndpoint()
        self.connection = FakeConnection()
        self.router = FakeRouter()
        self.is_connected = False
        self.calls = calls
        self.sent: list[Any] = []

    def start(self) -> None:
        self.calls.append("client:start")
        self.is_connected = True

    def stop(self) -> None:
        self.calls.append("client:stop")
        self.is_connected = False

    def subscribe(self, callback: Any, _message_filter: Any = None) -> Any:
        return self.router.messages.subscribe(callback)

    def wait_for(self, *_args: Any, **_kwargs: Any) -> Any:
        return "waited"

    def latest(self, _message_filter: Any = None) -> Any:
        return "latest"

    def send(self, message: Any) -> None:
        self.sent.append(message)

    def send_named(self, message_name: str, **parameters: Any) -> None:
        self.sent.append((message_name, parameters))


class ImmediateClient(FakeClient):
    def subscribe(self, callback: Any, _message_filter: Any = None) -> Any:
        subscription = self.router.messages.subscribe(callback)
        callback("immediate")
        return subscription


class FakePeer:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.packets = EventBus[MavlinkApplicationPacket]()
        self.errors = EventBus[Exception]()
        self.alive = True
        self.sent: list[tuple[str, Any]] = []

    def start(self) -> None:
        self.calls.append("peer:start")

    def stop(self) -> None:
        self.calls.append("peer:stop")

    def send(self, packet_type: str, payload: Any = None) -> MavlinkApplicationPacket:
        self.sent.append((packet_type, payload))
        return MavlinkApplicationPacket(packet_type, payload or {})

    def request(self, *_args: Any, **_kwargs: Any) -> str:
        return "response"


class FakeDispatcher:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.errors = EventBus[Exception]()
        self.handlers: dict[str, Any] = {}

    def start(self) -> None:
        self.calls.append("dispatcher:start")

    def stop(self) -> None:
        self.calls.append("dispatcher:stop")

    def register(self, packet_type: str, handler: Any, *, replace: bool = False) -> Any:
        self.handlers[packet_type] = handler
        return EventBus[None]().subscribe(lambda _event: None)


class FailingStopPeer(FakePeer):
    def __init__(self, calls: list[str]) -> None:
        super().__init__(calls)
        self.failures = 1

    def stop(self) -> None:
        super().stop()
        if self.failures:
            self.failures -= 1
            raise TimeoutError("peer still stopping")


class MavlinkRuntimeTests(unittest.TestCase):
    def test_same_thread_close_during_start_is_rejected_without_mixed_state(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client)
        original_start = client.start
        observed = []

        def start_and_close():
            original_start()
            try:
                runtime.close()
            except RuntimeError as error:
                observed.append(str(error))

        client.start = start_and_close
        runtime.start()
        try:
            self.assertTrue(runtime.running)
            self.assertTrue(client.is_connected)
            self.assertFalse(runtime._closed)
            self.assertEqual(len(observed), 1)
            self.assertIn("already active", observed[0])
        finally:
            runtime.close()
        self.assertTrue(runtime._closed)
        self.assertFalse(runtime.running)
        self.assertFalse(client.is_connected)

    def test_close_and_stop_wait_for_inflight_start(self):
        for operation in ("close", "stop"):
            with self.subTest(operation=operation):
                client = FakeClient([])
                entered, release, finished = threading.Event(), threading.Event(), threading.Event()
                original_start = client.start
                errors = []
                def start():
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError("Test did not release startup")
                    original_start()
                client.start = start
                runtime = MavlinkRuntime(client=client)
                def invoke(function):
                    try:
                        function()
                    except BaseException as error:
                        errors.append(error)
                def shutdown():
                    try:
                        invoke(getattr(runtime, operation))
                    finally:
                        finished.set()
                starter = threading.Thread(target=lambda: invoke(runtime.start))
                closer = threading.Thread(target=shutdown)
                starter.start()
                try:
                    self.assertTrue(entered.wait(1))
                    closer.start()
                    self.assertFalse(finished.wait(0.05))
                finally:
                    release.set()
                    starter.join(2)
                    if closer.ident is not None:
                        closer.join(2)
                    runtime.close()
                self.assertFalse(starter.is_alive())
                self.assertFalse(closer.is_alive())
                self.assertEqual(errors, [])
                self.assertFalse(runtime.running)
                self.assertFalse(client.is_connected)
                self.assertFalse(runtime._worker._thread.is_alive())

    def test_queued_telemetry_uses_subscribers_at_receipt(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client)
        entered, release = threading.Event(), threading.Event()
        runtime.start()
        try:
            emit(client, 12, 1)
            self.assertTrue(runtime._worker.wait_idle())
            vehicle = runtime.vehicles.get(12)
            first, late, cancelled = [], [], []
            vehicle.subscribe("ATTITUDE", first.append)
            removed = vehicle.get_component(1).subscribe("ATTITUDE", cancelled.append)
            runtime.subscribe("BLOCK", lambda event: (entered.set(), release.wait(2)))
            client.router.messages.publish(0)
            self.assertTrue(entered.wait(1))
            emit(client, 12, 1, "ATTITUDE")
            vehicle.subscribe("ATTITUDE", late.append)
            removed.cancel()
            release.set()
            self.assertTrue(runtime._worker.wait_idle())
            self.assertEqual(len(first), 1)
            self.assertEqual(late, [])
            self.assertEqual(cancelled, [])
            emit(client, 12, 1, "ATTITUDE")
            self.assertTrue(runtime._worker.wait_idle())
            self.assertEqual(len(late), 1)
        finally:
            release.set()
            runtime.close()

    def test_action_overflow_faults_sync_runtime_and_rejects_waits(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client, callback_action_capacity=1)
        entered, release = threading.Event(), threading.Event()
        runtime.subscribe("BLOCK", lambda event: (entered.set(), release.wait(2)))
        runtime.start()
        try:
            client.router.messages.publish(1)
            self.assertTrue(entered.wait(1))
            emit(client, 12, 1)
            self.assertIsInstance(runtime.delivery_error, BufferError)
            self.assertFalse(runtime.running)
            with self.assertRaises(RuntimeError):
                runtime.vehicles.wait_for(timeout=0)
            with self.assertRaises(RuntimeError):
                runtime.vehicles.get(12).wait_for("ATTITUDE", timeout=0)
            with self.assertRaises(RuntimeError):
                runtime.start()
        finally:
            release.set()
            runtime.close()

    def test_telemetry_cannot_evict_discovery_actions(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client, callback_capacity=2)
        entered, release = threading.Event(), threading.Event()
        added = []
        runtime.subscribe("BLOCK", lambda event: (entered.set(), release.wait(2)))
        runtime.vehicles.on_added(lambda event: added.append(event.vehicle.system_id))
        runtime.vehicles.subscribe("ATTITUDE", lambda event: None)
        runtime.start()
        try:
            client.router.messages.publish(0)
            self.assertTrue(entered.wait(1))
            emit(client, 12, 1)
            for _ in range(20):
                emit(client, 12, 1, "ATTITUDE")
            release.set()
            self.assertTrue(runtime._worker.wait_idle())
            self.assertEqual(added, [12])
            self.assertGreater(runtime.dropped_callbacks, 0)
        finally:
            release.set()
            runtime.close()

    def test_worker_fatal_exit_faults_runtime_and_restart_recovers(self):
        runtime = MavlinkRuntime(client=FakeClient([]))
        def fatal(event):
            raise SystemExit("worker exit")
        registration = runtime.subscribe("ANY", fatal)
        runtime.start()
        try:
            runtime.client.router.messages.publish(1)
            self.assertTrue(runtime._worker.wait_idle())
            self.assertFalse(runtime.running)
            self.assertIsInstance(runtime.delivery_error, RuntimeError)
            with self.assertRaises(RuntimeError):
                runtime.send_named("ANY")
            registration.cancel()
            runtime.stop()
            runtime.start()
            self.assertTrue(runtime.running)
        finally:
            runtime.close()
    def test_callback_worker_reports_stuck_shutdown_and_can_restart(self):
        from src.core.mavlink.delivery import CallbackWorker
        entered, release = threading.Event(), threading.Event()
        worker = CallbackWorker(2)
        worker.start()
        worker.submit(lambda event: (entered.set(), release.wait()), None)
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(TimeoutError):
                worker.stop()
            with self.assertRaises(RuntimeError):
                worker.start()
        finally:
            release.set()
            worker.stop()
        worker.start()
        try:
            received = []
            worker.submit(received.append, 1)
            self.assertTrue(worker.wait_idle())
            self.assertEqual(received, [1])
        finally:
            worker.stop()

    def test_slow_subscription_does_not_block_producer_and_overflow_is_bounded(self):
        client = FakeClient([])
        entered, release, published = threading.Event(), threading.Event(), threading.Event()
        runtime = MavlinkRuntime(client=client, callback_capacity=2)
        @runtime.subscribe("HEARTBEAT", max_calls=2)
        def callback(event):
            entered.set()
            release.wait(2)
        hooks = []
        callback.on_success(lambda context: hooks.append(context.event))
        runtime.start()
        try:
            client.router.messages.publish(0)
            self.assertTrue(entered.wait(1))
            def produce():
                for value in range(1, 101):
                    client.router.messages.publish(value)
                published.set()
            producer = threading.Thread(target=produce)
            producer.start()
            self.assertTrue(published.wait(1))
            producer.join(1)
            self.assertGreater(runtime.dropped_callbacks, 0)
            self.assertLessEqual(len(runtime._worker._queue), 2)
        finally:
            release.set()
            self.assertTrue(runtime._worker.wait_idle())
            runtime.close()
        self.assertEqual(len(hooks), 2)
        self.assertFalse(callback.active)

    def test_get_component_across_vehicles(self):
        client = FakeClient([])
        with MavlinkRuntime(client=client) as runtime:
            self.assertEqual(runtime.vehicles.get_component(1), ())
            emit(client, 12, 1)
            emit(client, 13, 1)
            emit(client, 13, 42)
            matches = runtime.vehicles.get_component(1)
            vehicle = runtime.vehicles.get(12)
            self.assertFalse(hasattr(vehicle, "components"))
            self.assertIsNone(vehicle.get_component(99))
            self.assertEqual(vehicle.get_components(), (vehicle.get_component(1),))
            self.assertEqual({item.system_id for item in matches}, {12, 13})
            self.assertIs(matches[0], runtime.vehicles.get(12).get_component(1))
            self.assertEqual(len(runtime.vehicles.get_component(42)), 1)
            emit(client, 14, 1)
            self.assertEqual(len(matches), 2)
            self.assertEqual(len(runtime.vehicles.get_component(1)), 3)
            for invalid in (0, 256, True, "1"):
                with self.assertRaises(ValueError):
                    runtime.vehicles.get_component(invalid)

    def test_concurrent_close_waits_for_cleanup(self):
        client = FakeClient([])
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        original_stop = client.stop

        def stop():
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Test did not release shutdown")
            original_stop()

        client.stop = stop
        runtime = MavlinkRuntime(client=client)
        runtime.start()
        first = threading.Thread(target=runtime.close)
        second = threading.Thread(target=lambda: (runtime.close(), completed.set()))
        first.start()
        try:
            self.assertTrue(entered.wait(1))
            second.start()
            self.assertFalse(completed.wait(0.05))
        finally:
            release.set()
            first.join(2)
            if second.ident is not None:
                second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(completed.is_set())
        self.assertFalse(client.is_connected)

    def test_sync_source_handlers_override_and_cancel_to_fallback(self):
        client, peer, dispatcher = FakeClient([]), FakePeer([]), FakeDispatcher([])
        runtime = MavlinkRuntime(client=client, peer=peer, dispatcher=dispatcher)
        runtime.handle("example.command", lambda packet: "global")
        with runtime:
            emit(client, 12, 1)
            vehicle = runtime.vehicles.get(12)
            vehicle.handle("example.command", lambda packet: "vehicle")
            scope = vehicle.get_component(1)
            registration = scope.handle("example.command", lambda packet: "component")
            packet = MavlinkApplicationPacket("example.command", {}, source_system=12, source_component=1)
            dispatch = dispatcher.handlers["example.command"]
            self.assertEqual(dispatch(packet), "component")
            registration.cancel()
            self.assertEqual(dispatch(packet), "vehicle")
            with self.assertRaises(ValueError):
                vehicle.handle("example.command", lambda packet: None)
            replacement = vehicle.handle("example.command", lambda packet: "new", replace=True)
            self.assertEqual(dispatch(packet), "new")
        self.assertFalse(replacement.active)

    def test_discovered_identity_is_read_only(self):
        runtime = MavlinkRuntime(client=FakeClient([]))
        with runtime:
            emit(runtime.client, 12, 1)
            vehicle = runtime.vehicles.get(12)
            component = vehicle.get_component(1)
            for node in (vehicle, component):
                for name, value in (("system_id", 13), ("component_id", 42), ("vehicle", None)):
                    with self.subTest(node=type(node).__name__, name=name):
                        with self.assertRaises(AttributeError):
                            setattr(node, name, value)

    def test_autopilot_is_reselected_after_removal_and_timeout(self):
        client = FakeClient([])
        client.connection.send_named = client.send_named
        with MavlinkRuntime(client=client) as runtime:
            emit(client, 12, 1)
            vehicle = runtime.vehicles.get(12)
            runtime._registry.expire(float("inf"))
            vehicle.remove_component(1)
            emit(client, 12, 2)
            vehicle.send_named("command_long", command=7)
            self.assertEqual(client.sent[-1][1]["target_component"], 2)
            runtime._registry.expire(float("inf"))
            emit(client, 12, 3)
            vehicle.send_named("command_long", command=7)
            self.assertEqual(client.sent[-1][1]["target_component"], 3)

    def test_stop_hook_cannot_restart_runtime_during_close(self):
        runtime = MavlinkRuntime(client=FakeClient([]))
        errors = []
        runtime.on_error(errors.append)
        runtime.on_stop(lambda event: runtime.start())
        runtime.start()
        runtime.close()
        self.assertFalse(runtime.running)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0].error, RuntimeError)

    def test_vehicle_request_sources_and_named_rate(self):
        client = FakeClient([])
        client.connection.send = client.send
        requests = []
        client.connection.request_message_rate = lambda *args, **kw: requests.append((args, kw))
        peer = FakePeer([])
        peer.request = lambda *args, **kw: requests.append((args, kw))
        runtime = MavlinkRuntime(client=client, peer=peer, dispatcher=FakeDispatcher([]))
        with runtime:
            emit(client, 12, 1)
            emit(client, 13, 1)
            vehicle = runtime.vehicles.get(13)
            original = SimpleNamespace(target_system=99, target_component=99)
            vehicle.send(original)
            self.assertEqual(original.target_system, 99)
            self.assertEqual(client.sent[-1].target_system, 13)
            self.assertEqual(client.sent[-1].target_component, 1)
            with self.assertRaises(ValueError):
                vehicle.send(object())
            vehicle.request_message_rate("HEARTBEAT", 2)
            self.assertEqual(requests[-1], ((0, 2), {"target_system": 13, "target_component": 1}))
            vehicle.request("mission.status", timeout=0.5)
            self.assertEqual(requests[-1][1]["target_system"], 13)
            self.assertEqual(requests[-1][1]["target_component"], 1)
            self.assertEqual(requests[-1][1]["timeout"], 0.5)

    def test_new_message_wait_and_collection_wait_wake_on_stop(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client)
        runtime.start()
        emit(client, 12, 1)
        vehicle = runtime.vehicles.get(12)
        self.assertIsNone(vehicle.wait_for("HEARTBEAT", timeout=0))
        results = []
        worker = threading.Thread(target=lambda: results.append(vehicle.wait_for("ATTITUDE")))
        worker.start()
        runtime.stop()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [None])
        runtime.close()

    def test_reentrant_discovery_close_does_not_deliver_more_messages(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client)
        received = []
        runtime.vehicles.on_added(lambda event: runtime.close())
        runtime.vehicles.subscribe("HEARTBEAT", received.append)
        runtime.start()
        emit(client, 12, 1)
        self.assertTrue(runtime._worker.wait_idle())
        self.assertFalse(runtime.running)
        self.assertEqual(received, [])

    def test_scope_subscriptions_cancel_once_and_close(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client, vehicle_history=2)
        with runtime:
            emit(client, 12, 1)
            vehicle = runtime.vehicles.get(12)
            calls = []
            subscription = vehicle.subscribe("ATTITUDE", calls.append, once=True)
            emit(client, 12, 1, "ATTITUDE")
            emit(client, 12, 1, "ATTITUDE")
            self.assertTrue(runtime._worker.wait_idle())
            self.assertEqual(len(calls), 1)
            self.assertFalse(subscription.active)
            self.assertEqual(len(vehicle.history()), 2)
            lingering = vehicle.on_error(calls.append)
        self.assertFalse(lingering.active)
        with self.assertRaises(RuntimeError):
            vehicle.subscribe("ATTITUDE", calls.append)

    def test_discovery_scopes_targets_and_reconnect_identity(self):
        client = FakeClient([])
        client.connection.send_named = client.send_named
        runtime = MavlinkRuntime(client=client)
        added, components, received, disconnected = [], [], [], []

        @runtime.vehicles.on_added
        def discover(event):
            added.append(event.vehicle)
            event.vehicle.on_component_added(components.append)

        runtime.vehicles.subscribe("ATTITUDE", received.append)
        runtime.start()
        try:
            emit(client, 12, 1)
            emit(client, 13, 1)
            emit(client, 12, 42, autopilot=8)
            self.assertTrue(runtime._worker.wait_idle())
            self.assertEqual(len(runtime.vehicles), 2)
            vehicle = runtime.vehicles.get(12)
            self.assertIs(runtime.vehicles.wait_for(timeout=0), vehicle)
            self.assertIsNone(runtime.vehicles.get(99))
            self.assertEqual(len(components), 3)
            specific, component_messages = [], []
            vehicle.subscribe("ATTITUDE", specific.append)
            vehicle.get_component(42).subscribe("ATTITUDE", component_messages.append)
            emit(client, 12, 42, "ATTITUDE")
            emit(client, 13, 1, "ATTITUDE")
            self.assertTrue(runtime._worker.wait_idle())
            self.assertEqual(len(received), 2)
            self.assertEqual(len(specific), 1)
            self.assertEqual(component_messages, specific)
            self.assertEqual(vehicle.latest("ATTITUDE").source_component, 42)
            self.assertEqual(runtime.vehicles.get(13).latest("ATTITUDE").source_system, 13)
            vehicle.send_named("command_long", command=7)
            self.assertEqual(client.sent[-1][1]["target_system"], 12)
            self.assertEqual(client.sent[-1][1]["target_component"], 1)
            vehicle.get_component(42).send_named("command_long", command=7)
            self.assertEqual(client.sent[-1][1]["target_component"], 42)
            with self.assertRaises(ValueError):
                vehicle.send_named("command_long", target_system=13)
            vehicle.on_disconnected(disconnected.append)
            runtime._registry.expire(float("inf"))
            self.assertTrue(runtime._worker.wait_idle())
            self.assertFalse(vehicle.state.connected)
            self.assertEqual(len(disconnected), 1)
            with self.assertRaises(RuntimeError):
                vehicle.send_named("command_long")
            emit(client, 12, 1)
            self.assertIs(runtime.vehicles.get(12), vehicle)
            self.assertTrue(vehicle.state.connected)
            with self.assertRaises(RuntimeError):
                runtime.vehicles.remove(12)
        finally:
            runtime.close()

    def test_collection_wait_shutdown_once_errors_and_gcs_exclusion(self):
        client = FakeClient([])
        runtime = MavlinkRuntime(client=client)
        runtime.start()
        result = []
        waiter = threading.Thread(target=lambda: result.append(runtime.vehicles.wait_for()))
        waiter.start()
        emit(client, 255, 1, autopilot=8)
        self.assertEqual(len(runtime.vehicles), 0)
        errors, calls = [], []
        runtime.vehicles.on_error(errors.append)
        runtime.vehicles.subscribe("ATTITUDE", lambda event: calls.append(event), once=True)
        runtime.vehicles.subscribe("ATTITUDE", lambda event: 1 / 0)
        emit(client, 12, 1)
        waiter.join(1)
        self.assertFalse(waiter.is_alive())
        self.assertIs(result[0], runtime.vehicles.get(12))
        emit(client, 12, 1, "ATTITUDE")
        emit(client, 12, 1, "ATTITUDE")
        self.assertTrue(runtime._worker.wait_idle())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(errors), 2)
        runtime.stop()
        self.assertIsNone(runtime.vehicles.wait_for(timeout=0))
        removed = []
        runtime.vehicles.on_removed(removed.append)
        self.assertTrue(runtime.vehicles.remove(12))
        self.assertEqual(len(removed), 1)
        runtime.close()

    def test_runtime_owns_lifecycle_in_dependency_order(self) -> None:
        calls: list[str] = []
        client = FakeClient(calls)
        peer = FakePeer(calls)
        dispatcher = FakeDispatcher(calls)
        runtime = MavlinkRuntime(
            client=client,  # type: ignore[arg-type]
            peer=peer,  # type: ignore[arg-type]
            dispatcher=dispatcher,  # type: ignore[arg-type]
        )

        runtime.start()
        runtime.stop()

        self.assertEqual(
            calls,
            [
                "client:start",
                "peer:start",
                "dispatcher:start",
                "dispatcher:stop",
                "peer:stop",
                "client:stop",
            ],
        )

    def test_simple_message_and_application_facade(self) -> None:
        calls: list[str] = []
        client = FakeClient(calls)
        peer = FakePeer(calls)
        dispatcher = FakeDispatcher(calls)
        runtime = MavlinkRuntime(
            client=client,  # type: ignore[arg-type]
            peer=peer,  # type: ignore[arg-type]
            dispatcher=dispatcher,  # type: ignore[arg-type]
        )
        received: list[Any] = []
        runtime.start()
        self.addCleanup(runtime.close)
        runtime.once("HEARTBEAT", received.append)

        client.router.messages.publish("first")
        client.router.messages.publish("second")
        self.assertTrue(runtime._worker.wait_idle())
        packet = runtime.notify("mission.status", {"ready": True})
        runtime.handle("mission.start", lambda _packet: None)

        self.assertEqual(received, ["first"])
        self.assertEqual(packet.packet_type, "mission.status")
        self.assertIn("mission.start", dispatcher.handlers)
        self.assertEqual(runtime.request("mission.start"), "response")
        self.assertEqual(runtime.latest("ATTITUDE"), "latest")
        self.assertEqual(runtime.wait_for("GPS_RAW_INT"), "waited")

    def test_once_cancels_subscription_when_delivery_is_immediate(self) -> None:
        calls: list[str] = []
        client = ImmediateClient(calls)
        runtime = MavlinkRuntime(client=client)  # type: ignore[arg-type]
        received: list[Any] = []

        subscription = runtime.once("HEARTBEAT", received.append)
        # Registration before start cannot execute a receive callback.
        self.assertEqual(received, [])
        runtime.start()
        self.addCleanup(runtime.close)
        client.router.messages.publish("immediate")
        self.assertTrue(runtime._worker.wait_idle())
        self.assertEqual(received, ["immediate"])
        self.assertFalse(subscription.active)
        self.assertEqual(client.router.messages.subscriber_count, 0)

    def test_runtime_unifies_component_errors_and_reports_state(self) -> None:
        calls: list[str] = []
        client = FakeClient(calls)
        runtime = MavlinkRuntime(client=client)  # type: ignore[arg-type]
        errors: list[Any] = []
        runtime.errors.subscribe(errors.append)

        client.connection.errors.publish(RuntimeError("transport failed"))
        runtime.start()
        state = runtime.state
        runtime.stop()

        self.assertEqual(errors[0].source, "connection")
        self.assertEqual(str(errors[0].error), "transport failed")
        self.assertTrue(state.running)
        self.assertTrue(state.connected)
        self.assertFalse(state.application_enabled)

    def test_application_role_builds_default_stack_without_connecting(self) -> None:
        runtime = MavlinkRuntime(
            MavlinkEndpoint.udp("127.0.0.1", 14550),
            application_role="vehicle",
        )

        self.assertTrue(runtime.application_enabled)
        self.assertIsNotNone(runtime.channel)
        self.assertIsNotNone(runtime.peer)
        self.assertIsNotNone(runtime.dispatcher)
        runtime.close()

    def test_failed_shutdown_is_reported_and_can_be_retried(self) -> None:
        calls: list[str] = []
        client = FakeClient(calls)
        peer = FailingStopPeer(calls)
        dispatcher = FakeDispatcher(calls)
        runtime = MavlinkRuntime(
            client=client,  # type: ignore[arg-type]
            peer=peer,  # type: ignore[arg-type]
            dispatcher=dispatcher,  # type: ignore[arg-type]
        )
        runtime.start()

        with self.assertRaises(ExceptionGroup):
            runtime.stop()
        self.assertIn("client:stop", calls)

        runtime.close()
        self.assertTrue(runtime.errors.closed)
        self.assertEqual(calls.count("peer:stop"), 2)


class WireMessage:
    def __init__(self, system, component, message_type="HEARTBEAT", autopilot=3):
        self.system, self.component, self.message_type = system, component, message_type
        self.autopilot = autopilot
        self.type = 2

    def get_type(self):
        return self.message_type

    def get_srcSystem(self):
        return self.system

    def get_srcComponent(self):
        return self.component

    def get_msgId(self):
        return 0


def emit(client, system, component, message_type="HEARTBEAT", autopilot=3):
    message = WireMessage(system, component, message_type, autopilot)
    client.router.envelopes.publish(MavlinkMessageEnvelope.wrap(1, message))


class AsyncMavlinkRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_subscription_decorator_has_local_hooks_and_settings(self):
        client = FakeClient([])
        async with AsyncMavlinkRuntime(client=client) as runtime:
            done = asyncio.Event()
            calls = []
            @runtime.subscribe("HEARTBEAT", enabled=False, once=True, timeout=1,
                               predicate=lambda value: value > 0, frequency_hz=10)
            async def receive(value):
                calls.append(value)
            @receive.on_success
            async def success(context):
                calls.append("success")
            @receive.on_after
            async def after(context):
                done.set()
            receive.enable()
            client.router.messages.publish(-1)
            client.router.messages.publish(1)
            client.router.messages.publish(2)
            await asyncio.wait_for(done.wait(), 1)
            self.assertEqual(calls, [1, "success"])
            self.assertFalse(receive.active)

    async def test_delivery_fault_rejects_runtime_and_scoped_operations(self):
        client = FakeClient([])
        runtime = AsyncMavlinkRuntime(client=client, action_capacity=32)
        await runtime.start()
        try:
            emit(client, 12, 1)
            emit(client, 13, 1)
            components = runtime.vehicles.get_component(1)
            self.assertEqual({item.system_id for item in components}, {12, 13})
            vehicle = runtime.vehicles.get(12)
            pending = asyncio.create_task(vehicle.wait_for("EXAMPLE"))
            self.assertFalse(hasattr(vehicle, "components"))
            self.assertIsNone(vehicle.get_component(99))
            self.assertIs(await vehicle.wait_for_component(timeout=0), vehicle.get_component(1))
            await asyncio.sleep(0)
            # A discovery burst fills the lifecycle queue without yielding.
            for system_id in range(14, 24):
                emit(client, system_id, 1)
            self.assertIsInstance(runtime.delivery_error, BufferError)
            with self.assertRaises(RuntimeError):
                await asyncio.wait_for(pending, 1)
            operations = (
                lambda: runtime.send(object()),
                lambda: runtime.send_named("EXAMPLE"),
                lambda: runtime.notify("example"),
                lambda: runtime.request("example"),
                lambda: runtime.wait_for("EXAMPLE"),
                lambda: runtime.vehicles.wait_for(timeout=0),
                lambda: vehicle.wait_for_component(timeout=0),
                lambda: vehicle.wait_for("EXAMPLE"),
                lambda: components[0].send_named("EXAMPLE"),
            )
            for operation in operations:
                with self.assertRaises(RuntimeError):
                    await operation()
            self.assertEqual(client.sent, [])
            self.assertIs(runtime.vehicles.get(12), vehicle)
            await runtime.stop()
            await runtime.start()
            await runtime.send_named("EXAMPLE")
            self.assertEqual(len(client.sent), 1)
            self.assertIsNone(runtime.delivery_error)
        finally:
            await runtime.close()

    async def test_raw_once_releases_subscription(self):
        client = FakeClient([])
        runtime = AsyncMavlinkRuntime(client=client)
        received = []
        delivered = asyncio.Event()

        async def callback(message):
            received.append(message)
            delivered.set()

        async with runtime:
            subscription = runtime.once("HEARTBEAT", callback)
            client.router.messages.publish("first")
            client.router.messages.publish("second")
            await asyncio.wait_for(delivered.wait(), 1)
            self.assertEqual(received, ["first"])
            self.assertFalse(subscription.active)
            self.assertNotIn(subscription, runtime._raw_subscriptions)

    async def test_cancelling_close_caller_does_not_cancel_cleanup(self):
        client = FakeClient([])
        runtime = AsyncMavlinkRuntime(client=client)
        entered, release = threading.Event(), threading.Event()
        original_stop = client.stop

        def stop():
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Test did not release shutdown")
            original_stop()

        client.stop = stop
        await runtime.start()
        caller = asyncio.create_task(runtime.close())
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertFalse(runtime._close_task.done())
        finally:
            release.set()
            await runtime.close()
        self.assertFalse(client.is_connected)
        self.assertTrue(runtime.messages.closed)

    async def test_runtime_api_and_raw_async_streams(self):
        client, peer, dispatcher = FakeClient([]), FakePeer([]), FakeDispatcher([])
        runtime = AsyncMavlinkRuntime(client=client, peer=peer, dispatcher=dispatcher)
        for name in ("handle", "subscribe", "once", "wait_for", "latest", "send", "send_named",
                     "request", "notify", "messages", "packets", "errors", "client", "connection", "router"):
            self.assertTrue(hasattr(runtime, name), name)
        raw, packets = asyncio.Event(), asyncio.Event()
        async def message(event):
            raw.set()
        async def packet(event):
            packets.set()
        await runtime.messages.subscribe(message)
        await runtime.packets.subscribe(packet)
        async with runtime:
            client.router.messages.publish("raw")
            peer.packets.publish(MavlinkApplicationPacket("example.packet", {}))
            await asyncio.wait_for(raw.wait(), 1)
            await asyncio.wait_for(packets.wait(), 1)
            self.assertEqual(await runtime.wait_for("HEARTBEAT"), "waited")
            self.assertEqual(await runtime.request("example.request"), "response")
            self.assertEqual((await runtime.notify("example.notice")).packet_type, "example.notice")
        self.assertTrue(runtime.messages.closed)
        self.assertTrue(runtime.packets.closed)

    async def test_async_application_handler_is_cancelled_and_joined_at_shutdown(self):
        client, peer, dispatcher = FakeClient([]), FakePeer([]), FakeDispatcher([])
        runtime = AsyncMavlinkRuntime(client=client, peer=peer, dispatcher=dispatcher)
        entered, finished = asyncio.Event(), asyncio.Event()
        @runtime.handle("example.command")
        async def handler(packet):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        await runtime.start()
        invocation = asyncio.create_task(asyncio.to_thread(
            dispatcher.handlers["example.command"], MavlinkApplicationPacket("example.command", {}),
        ))
        await asyncio.wait_for(entered.wait(), 1)
        await runtime.close()
        self.assertTrue(finished.is_set())
        self.assertFalse(runtime._runtime._application_handlers._tasks)
        with self.assertRaises(asyncio.CancelledError):
            await invocation

    async def test_action_overflow_is_an_explicit_fault(self):
        runtime = AsyncMavlinkRuntime(client=FakeClient([]), action_capacity=1)
        await runtime.start()
        try:
            emit(runtime.client, 12, 1)
            self.assertIsInstance(runtime.delivery_error, BufferError)
            self.assertFalse(runtime.running)
            self.assertFalse(runtime.state.running)
        finally:
            await runtime.close()

    async def test_cancelled_callback_does_not_kill_delivery(self):
        client = FakeClient([])
        runtime = AsyncMavlinkRuntime(client=client)
        failed = asyncio.Event()
        healthy = asyncio.Event()

        @runtime.vehicles.subscribe("ATTITUDE")
        async def cancelled(event):
            failed.set()
            raise asyncio.CancelledError()

        @runtime.vehicles.subscribe("HEARTBEAT")
        async def receive(event):
            healthy.set()

        async with runtime:
            emit(client, 12, 1)
            await asyncio.wait_for(healthy.wait(), 1)
            healthy.clear()
            emit(client, 12, 1, "ATTITUDE")
            await asyncio.wait_for(failed.wait(), 1)
            emit(client, 12, 1)
            await asyncio.wait_for(healthy.wait(), 1)
            self.assertFalse(runtime._delivery._task.done())

    async def test_discovery_survives_telemetry_overflow_and_installs_actions(self):
        client = FakeClient([])
        runtime = AsyncMavlinkRuntime(client=client, delivery_capacity=1)
        calls = []
        connected = asyncio.Event()

        @runtime.vehicles.on_added
        async def added(event):
            calls.append("added")
            @event.vehicle.on_connected
            async def connection(event):
                calls.append("connected")
                connected.set()
            @event.vehicle.on_component_added
            async def component(event):
                calls.append("component")

        @runtime.vehicles.subscribe("HEARTBEAT")
        async def receive(event):
            pass

        async with runtime:
            emit(client, 12, 1)
            for _ in range(10):
                emit(client, 12, 1)
            await asyncio.wait_for(connected.wait(), 1)
            self.assertEqual(calls, ["added", "component", "connected"])

    async def test_concurrent_close_waits_for_the_same_cleanup(self):
        client = FakeClient([])
        entered, release = threading.Event(), threading.Event()
        original_stop = client.stop
        def stop():
            entered.set()
            release.wait(2)
            original_stop()
        client.stop = stop
        runtime = AsyncMavlinkRuntime(client=client)
        await runtime.start()
        first = asyncio.create_task(runtime.close())
        await asyncio.to_thread(entered.wait, 1)
        second = asyncio.create_task(runtime.close())
        try:
            for _ in range(5):
                await asyncio.sleep(0)
            self.assertFalse(second.done())
        finally:
            release.set()
            await asyncio.gather(first, second)
        self.assertFalse(client.is_connected)

    async def test_async_application_handlers_are_source_scoped(self):
        client = FakeClient([])
        peer, dispatcher = FakePeer([]), FakeDispatcher([])
        runtime = AsyncMavlinkRuntime(client=client, peer=peer, dispatcher=dispatcher)
        loop_thread = threading.get_ident()

        @runtime.handle("example.command")
        async def default(packet):
            return {"handler": "default"}

        async with runtime:
            emit(client, 12, 1)
            emit(client, 13, 1)
            vehicle = runtime.vehicles.get(12)
            @vehicle.handle("example.command")
            async def specific(packet):
                self.assertEqual(threading.get_ident(), loop_thread)
                return {"handler": "vehicle"}
            @vehicle.get_component(1).handle("example.command")
            async def component(packet):
                return {"handler": "component"}
            dispatch = dispatcher.handlers["example.command"]
            for system, component_id, expected in ((12, 1, "component"), (12, 42, "vehicle"), (13, 1, "default")):
                packet = MavlinkApplicationPacket("example.command", {}, source_system=system, source_component=component_id)
                result = await asyncio.to_thread(dispatch, packet)
                self.assertEqual(result["handler"], expected)

    async def test_cancelled_start_hook_cleans_up_transport(self):
        runtime = AsyncMavlinkRuntime(client=FakeClient([]))
        entered = asyncio.Event()

        @runtime.on_start
        async def start(event):
            entered.set()
            await asyncio.Event().wait()

        starting = asyncio.create_task(runtime.start())
        await asyncio.wait_for(entered.wait(), 1)
        starting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await starting
        self.assertFalse(runtime.running)
        self.assertIsNone(runtime._delivery._task)
        await runtime.close()

    async def test_stop_hook_cannot_restart_async_runtime_during_close(self):
        runtime = AsyncMavlinkRuntime(client=FakeClient([]))
        errors = []

        @runtime.on_error
        async def error(event):
            errors.append(event.error)

        @runtime.on_stop
        async def stop(event):
            await runtime.start()

        await runtime.start()
        await runtime.close()
        self.assertFalse(runtime.running)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)

    async def test_lifecycle_actions_are_awaited_and_once_is_consumed(self):
        runtime = AsyncMavlinkRuntime(client=FakeClient([]))
        calls = []

        @runtime.on_start
        async def start(event):
            await asyncio.sleep(0)
            calls.append("start")

        @runtime.on_stop(once=True)
        async def stop(event):
            await asyncio.sleep(0)
            calls.append("stop")

        await runtime.start()
        self.assertEqual(calls, ["start"])
        await runtime.stop()
        self.assertEqual(calls, ["start", "stop"])
        await runtime.start()
        await runtime.close()
        self.assertEqual(calls, ["start", "stop", "start"])

    async def test_async_message_wait_does_not_depend_on_callback_consumer(self):
        client = FakeClient([])
        runtime = AsyncMavlinkRuntime(client=client)
        completed = asyncio.Event()

        @runtime.vehicles.on_added
        async def added(event):
            message = await event.vehicle.wait_for("ATTITUDE", timeout=1)
            self.assertEqual(message.source_system, 12)
            completed.set()

        await runtime.start()
        emit(client, 12, 1)
        # Wait for registration of the actual message waiter, not a timed sleep.
        for _ in range(100):
            if runtime._runtime._registry.message_waiters:
                break
            await asyncio.sleep(0)
        self.assertTrue(runtime._runtime._registry.message_waiters)
        emit(client, 13, 1)
        emit(client, 13, 1, "ATTITUDE")
        emit(client, 12, 1, "ATTITUDE")
        await asyncio.wait_for(completed.wait(), 1)
        await runtime.close()

    async def test_async_discovery_decorators_targeting_and_context_cleanup(self):
        client = FakeClient([])
        client.connection.send_named = client.send_named
        runtime = AsyncMavlinkRuntime(client=client)
        received = asyncio.Event()
        callback_thread = []

        @runtime.vehicles.subscribe("ATTITUDE")
        async def attitude(event):
            callback_thread.append(threading.get_ident())
            received.set()

        async with runtime:
            pending = asyncio.create_task(runtime.vehicles.wait_for(timeout=1))
            await asyncio.sleep(0)
            await asyncio.to_thread(emit, client, 12, 1)
            vehicle = await pending
            self.assertIs(vehicle, runtime.vehicles.get(12))
            component = await vehicle.wait_for_component(timeout=0)
            await component.send_named("command_long", command=7)
            self.assertEqual(client.sent[-1][1]["target_system"], 12)
            await vehicle.send_named("command_long", command=8)
            await asyncio.to_thread(emit, client, 12, 1, "ATTITUDE")
            await asyncio.wait_for(received.wait(), 1)
            self.assertEqual(callback_thread, [threading.get_ident()])
            with self.assertRaises(TypeError):
                vehicle.on_connected(lambda event: None)
        self.assertFalse(runtime.running)
        self.assertFalse(vehicle.state.connected)
        self.assertIsNone(runtime._delivery._task)

    async def test_wait_cancellation_timeout_and_stop_wake(self):
        runtime = AsyncMavlinkRuntime(client=FakeClient([]))
        await runtime.start()
        self.assertIsNone(await runtime.vehicles.wait_for(timeout=0.001))
        waiting = asyncio.create_task(runtime.vehicles.wait_for())
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertFalse(runtime._runtime._registry.waiters)
        waiting = asyncio.create_task(runtime.vehicles.wait_for())
        await asyncio.sleep(0)
        await runtime.stop()
        self.assertIsNone(await asyncio.wait_for(waiting, 1))
        await runtime.start()
        self.assertTrue(runtime.running)
        await runtime.close()

    async def test_bounded_delivery_cancellation_and_restart(self):
        client = FakeClient([])
        runtime = AsyncMavlinkRuntime(client=client, delivery_capacity=2)
        calls = []

        async def receive(event):
            calls.append(event)

        subscription = runtime.vehicles.subscribe("ATTITUDE", receive)
        await runtime.start()
        emit(client, 12, 1)
        for _ in range(10):
            emit(client, 12, 1, "ATTITUDE")
        self.assertEqual(runtime.dropped_callbacks, 8)
        subscription.cancel()
        await asyncio.sleep(0)
        await runtime.stop()
        await runtime.start()
        await asyncio.sleep(0)
        self.assertEqual(calls, [])
        await runtime.close()
