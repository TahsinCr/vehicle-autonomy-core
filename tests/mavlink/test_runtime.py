from __future__ import annotations

import unittest
from typing import Any

from src.core.events import EventBus
from src.core.compatibility import ExceptionGroup
from src.core.mavlink import (
    MavlinkApplicationPacket,
    MavlinkEndpoint,
    MavlinkRuntime,
    MavlinkRouterStats,
)


class FakeConnection:
    def __init__(self) -> None:
        self.errors = EventBus[Exception]()
        self.target_system = 1
        self.target_component = 1


class FakeRouter:
    def __init__(self) -> None:
        self.messages = EventBus[Any]()
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
        runtime.once("HEARTBEAT", received.append)

        client.router.messages.publish("first")
        client.router.messages.publish("second")
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
