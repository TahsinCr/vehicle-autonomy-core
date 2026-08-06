from __future__ import annotations

import asyncio
import queue
import threading
import time
import unittest
from typing import Any

from src.core.events import EventBus
from src.core.mavlink.application import MavlinkApplicationPacket
from src.core.mavlink.channel import MavlinkAsyncChannel
from src.core.mavlink.dispatch import MavlinkApplicationDispatcher
from src.core.mavlink.peer import MavlinkApplicationPeer
from src.core.mavlink.router import MavlinkMessageRouter


class _Message:
    def __init__(self, message_type: str, value: int = 0) -> None:
        self._message_type = message_type
        self.value = value

    def get_type(self) -> str:
        return self._message_type


class _RestartableConnection:
    def __init__(self) -> None:
        self.inbox: queue.Queue[_Message] = queue.Queue()
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> None:
        self.start_count += 1

    def stop(self) -> None:
        self.stop_count += 1

    def receive(self, *, blocking: bool = False, timeout: float | None = None) -> Any:
        del blocking
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def evaluate_condition(self, _condition: str) -> bool:
        return True


class _StuckConnection(_RestartableConnection):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def receive(self, *, blocking: bool = False, timeout: float | None = None) -> None:
        del blocking, timeout
        self.entered.set()
        self.release.wait()
        return None


class RouterLifecycleTests(unittest.TestCase):
    def test_router_can_start_stop_and_restart(self) -> None:
        connection = _RestartableConnection()
        router = MavlinkMessageRouter(
            connection,  # type: ignore[arg-type]
            poll_timeout=0.01,
            stop_timeout=0.2,
        )

        router.start()
        router.stop()
        router.start()
        boundary = router.sequence
        connection.inbox.put(_Message("HEARTBEAT", 9))
        message = router.wait_for("HEARTBEAT", timeout=1.0, after_sequence=boundary)
        router.stop()

        self.assertEqual(message.value, 9)
        self.assertEqual(connection.start_count, 2)
        self.assertEqual(connection.stop_count, 2)
        self.assertFalse(router.running)

    def test_router_keeps_connection_open_when_receive_thread_is_stuck(self) -> None:
        connection = _StuckConnection()
        router = MavlinkMessageRouter(
            connection,  # type: ignore[arg-type]
            poll_timeout=0.01,
            stop_timeout=0.05,
        )
        router.start()
        self.assertTrue(connection.entered.wait(1.0))

        with self.assertRaisesRegex(TimeoutError, "receive thread"):
            router.stop()

        self.assertEqual(connection.stop_count, 0)
        self.assertTrue(router.running)
        with self.assertRaisesRegex(RuntimeError, "durduruluyor"):
            router.start()

        connection.release.set()
        router.stop()
        self.assertEqual(connection.stop_count, 1)
        self.assertFalse(router.running)


class _RouterStub:
    def __init__(self) -> None:
        self.messages = EventBus[Any]()

    def subscribe(self, callback: Any, _message_filter: Any = None) -> Any:
        return self.messages.subscribe(callback)


class _ClosingLoop:
    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, _callback: Any, _message: Any) -> None:
        raise RuntimeError("event loop closed during scheduling")


class AsyncChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_overflow_drops_oldest_and_stop_clears_session(self) -> None:
        router = _RouterStub()
        channel = MavlinkAsyncChannel(router, maxsize=1)  # type: ignore[arg-type]
        channel.start()

        first = _Message("A", 1)
        second = _Message("A", 2)
        router.messages.publish(first)
        router.messages.publish(second)
        await asyncio.sleep(0)

        self.assertEqual(channel.dropped_messages, 1)
        self.assertIs(channel.receive_nowait(), second)

        router.messages.publish(first)
        await asyncio.sleep(0)
        channel.stop()
        channel.start()
        with self.assertRaises(asyncio.TimeoutError):
            await channel.receive(timeout=0.01)
        channel.stop()

    async def test_closed_loop_race_is_ignored(self) -> None:
        channel = MavlinkAsyncChannel(
            _RouterStub(),  # type: ignore[arg-type]
            loop=_ClosingLoop(),  # type: ignore[arg-type]
        )
        channel._forward(_Message("HEARTBEAT"))


class _ChannelStub:
    def __init__(self) -> None:
        self.packets = EventBus[MavlinkApplicationPacket]()
        self.errors = EventBus[Exception]()
        self.sent: list[MavlinkApplicationPacket] = []
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def send(
        self,
        packet_type: str,
        payload: Any = None,
        *,
        packet_id: int | None = None,
        expects_response: bool = False,
        **_targets: Any,
    ) -> MavlinkApplicationPacket:
        packet = MavlinkApplicationPacket(
            packet_type,
            dict(payload or {}),
            packet_id=packet_id or len(self.sent) + 1,
            expects_response=expects_response,
        )
        self.sent.append(packet)
        return packet


class PeerLifecycleTests(unittest.TestCase):
    def _peer(self, channel: _ChannelStub, **options: Any) -> MavlinkApplicationPeer:
        return MavlinkApplicationPeer(
            channel,  # type: ignore[arg-type]
            role="onboard",
            heartbeat_interval=0.02,
            heartbeat_timeout=0.2,
            stop_timeout=0.1,
            **options,
        )

    def test_stop_wakes_pending_request_and_prevents_later_packets(self) -> None:
        channel = _ChannelStub()
        peer = self._peer(channel)
        peer.start()
        sent = threading.Event()
        errors: list[Exception] = []

        def request() -> None:
            try:
                peer.request(
                    "camera.capture",
                    response_types="system.ack",
                    timeout=2.0,
                    on_sent=lambda _packet: sent.set(),
                )
            except Exception as exc:
                errors.append(exc)

        requester = threading.Thread(target=request)
        requester.start()
        self.assertTrue(sent.wait(1.0))
        peer.stop()
        requester.join(1.0)
        sent_count = len(channel.sent)
        time.sleep(0.05)

        self.assertFalse(requester.is_alive())
        self.assertIsInstance(errors[0], ConnectionError)
        self.assertEqual(len(channel.sent), sent_count)
        self.assertFalse(peer.running)

    def test_stuck_monitor_thread_is_reported_and_retained(self) -> None:
        channel = _ChannelStub()
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def transport_available() -> bool:
            nonlocal calls
            calls += 1
            if calls == 1:
                return True
            entered.set()
            release.wait()
            return True

        peer = self._peer(channel, transport_available=transport_available)
        peer.start()
        self.assertTrue(entered.wait(1.0))

        with self.assertRaisesRegex(TimeoutError, "monitor thread"):
            peer.stop()

        stopped_state = peer.state
        sent_count = len(channel.sent)
        self.assertIsNotNone(peer._monitor_thread)
        self.assertFalse(peer.running)
        with self.assertRaisesRegex(RuntimeError, "still stopping"):
            peer.start()
        release.set()
        peer.stop()
        self.assertIsNone(peer._monitor_thread)
        self.assertEqual(peer.state, stopped_state)
        self.assertEqual(len(channel.sent), sent_count)

    def test_request_accepts_only_correlated_response(self) -> None:
        channel = _ChannelStub()
        peer = self._peer(channel)
        peer.start()
        sent = threading.Event()
        requests: list[MavlinkApplicationPacket] = []
        responses: list[Any] = []

        def request() -> None:
            responses.append(
                peer.request(
                    "camera.capture",
                    response_types="system.ack",
                    timeout=1.0,
                    on_sent=lambda packet: (requests.append(packet), sent.set()),
                )
            )

        requester = threading.Thread(target=request)
        requester.start()
        self.assertTrue(sent.wait(1.0))
        channel.packets.publish(
            MavlinkApplicationPacket(
                "system.ack",
                {"request_id": requests[0].packet_id + 1},
            )
        )
        self.assertTrue(requester.is_alive())
        channel.packets.publish(
            MavlinkApplicationPacket(
                "system.ack",
                {"request_id": requests[0].packet_id, "accepted": True},
            )
        )
        requester.join(1.0)
        peer.stop()

        self.assertFalse(requester.is_alive())
        self.assertEqual(responses[0].response.payload["accepted"], True)

    def test_request_timeout_and_liveness_expiry(self) -> None:
        channel = _ChannelStub()
        peer = self._peer(channel)
        peer.start()

        with self.assertRaises(TimeoutError):
            peer.request(
                "camera.capture",
                response_types="system.ack",
                timeout=0.02,
            )

        channel.packets.publish(MavlinkApplicationPacket("system.heartbeat"))
        self.assertTrue(peer.alive)
        deadline = time.monotonic() + 0.5
        while peer.alive and time.monotonic() < deadline:
            time.sleep(0.01)
        peer.stop()

        self.assertFalse(peer.alive)


class _PeerStub:
    def __init__(self) -> None:
        self.packets = EventBus[MavlinkApplicationPacket]()
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send(self, packet_type: str, payload: Any, **_targets: Any) -> None:
        self.sent.append((packet_type, dict(payload)))


class DispatcherLifecycleTests(unittest.TestCase):
    def test_stop_suppresses_running_handler_response_and_releases_capacity(self) -> None:
        peer = _PeerStub()
        dispatcher = MavlinkApplicationDispatcher(
            peer,  # type: ignore[arg-type]
            workers=1,
            max_pending=1,
        )
        entered = threading.Event()
        release = threading.Event()

        def handler(_packet: MavlinkApplicationPacket) -> dict[str, bool]:
            entered.set()
            release.wait()
            return {"done": True}

        dispatcher.register("camera.capture", handler)
        dispatcher.start()
        first = MavlinkApplicationPacket(
            "camera.capture", packet_id=101, expects_response=True
        )
        second = MavlinkApplicationPacket(
            "camera.capture", packet_id=102, expects_response=True
        )
        self.assertTrue(dispatcher.dispatch(first))
        self.assertTrue(entered.wait(1.0))
        self.assertFalse(dispatcher.dispatch(second))

        stopper = threading.Thread(target=dispatcher.stop)
        stopper.start()
        time.sleep(0.02)
        self.assertTrue(stopper.is_alive())
        release.set()
        stopper.join(1.0)

        self.assertFalse(stopper.is_alive())
        response_ids = [payload["request_id"] for _, payload in peer.sent]
        self.assertIn(102, response_ids)
        self.assertNotIn(101, response_ids)

        dispatcher.start()
        handled = threading.Event()
        dispatcher.handled.subscribe(lambda _result: handled.set())
        self.assertTrue(
            dispatcher.dispatch(MavlinkApplicationPacket("camera.capture", packet_id=103))
        )
        self.assertTrue(handled.wait(1.0))
        dispatcher.stop()


if __name__ == "__main__":
    unittest.main()
