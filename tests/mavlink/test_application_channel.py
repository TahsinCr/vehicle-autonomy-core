from __future__ import annotations

import types
import unittest
from collections.abc import Callable

from src.core.events import Subscription
from src.core.mavlink.application import (
    DEFAULT_APPLICATION_MESSAGE_TYPE,
    DEFAULT_APPLICATION_NETWORK,
    MavlinkApplicationChannel,
    MavlinkApplicationCodec,
    MavlinkApplicationPacket,
)
from src.core.mavlink.filter import MavlinkMessageFilter


class _ExtensionMessage:
    id = 248
    msgname = "V2_EXTENSION"
    fieldnames: list[str] = []

    def __init__(
        self,
        payload: bytes,
        *,
        source_system: int = 4,
        source_component: int = 5,
        target_network: int = DEFAULT_APPLICATION_NETWORK,
        target_system: int = 0,
        target_component: int = 0,
        message_type: int = DEFAULT_APPLICATION_MESSAGE_TYPE,
    ) -> None:
        self.payload = payload
        self.target_network = target_network
        self.target_system = target_system
        self.target_component = target_component
        self.message_type = message_type
        self._source_system = source_system
        self._source_component = source_component

    def get_type(self) -> str:
        return "V2_EXTENSION"

    def get_srcSystem(self) -> int:
        return self._source_system

    def get_srcComponent(self) -> int:
        return self._source_component

    def get_msgId(self) -> int:
        return self.id


class _Client:
    def __init__(self) -> None:
        self.endpoint = types.SimpleNamespace(source_system=12, source_component=34)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._listeners: list[tuple[Callable[[_ExtensionMessage], None], MavlinkMessageFilter]] = []

    def subscribe(
        self,
        callback: Callable[[_ExtensionMessage], None],
        message_filter: MavlinkMessageFilter,
    ) -> Subscription:
        entry = (callback, message_filter)
        self._listeners.append(entry)
        return Subscription(1, lambda: self._listeners.remove(entry))

    def call_mav(self, method: str, *arguments: object) -> None:
        self.calls.append((method, arguments))

    def emit(self, message: _ExtensionMessage) -> None:
        for callback, message_filter in tuple(self._listeners):
            if message_filter.matches(message):
                callback(message)


class ApplicationChannelTests(unittest.TestCase):
    def test_channel_routes_matching_packets_and_clears_assemblies_on_stop(self) -> None:
        client = _Client()
        channel = MavlinkApplicationChannel(client)  # type: ignore[arg-type]
        received: list[MavlinkApplicationPacket] = []
        channel.packets.subscribe(received.append)

        channel.start()
        channel.start()
        packet = MavlinkApplicationPacket("camera.capture", {"mode": "photo"})
        for fragment in MavlinkApplicationCodec.encode(packet):
            client.emit(_ExtensionMessage(fragment))

        self.assertTrue(channel.running)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].packet_type, "camera.capture")
        self.assertEqual(received[0].source_system, 4)
        channel.stop()
        self.assertFalse(channel.running)
        self.assertFalse(client._listeners)
        self.assertFalse(channel._assembler._assemblies)

    def test_channel_filters_addresses_reports_decode_errors_and_sends_targets(self) -> None:
        client = _Client()
        channel = MavlinkApplicationChannel(
            client,  # type: ignore[arg-type]
            local_system=12,
            local_component=34,
            source_systems=4,
        )
        errors: list[Exception] = []
        received: list[MavlinkApplicationPacket] = []
        channel.errors.subscribe(errors.append)
        channel.packets.subscribe(received.append)
        channel.start()

        client.emit(_ExtensionMessage(b"invalid"))
        client.emit(_ExtensionMessage(b"invalid", source_system=9))
        client.emit(_ExtensionMessage(b"invalid", target_system=99))
        self.assertEqual(len(errors), 1)
        self.assertFalse(received)

        packet = channel.send(
            "camera.capture",
            {"quality": "high"},
            packet_id=99,
            target_system=7,
            target_component=8,
            expects_response=True,
        )
        self.assertTrue(packet.expects_response)
        self.assertTrue(client.calls)
        method, arguments = client.calls[0]
        self.assertEqual(method, "v2_extension_send")
        self.assertEqual(arguments[1:4], (7, 8, DEFAULT_APPLICATION_MESSAGE_TYPE))

        with self.assertRaises(ValueError):
            channel.send("camera.capture", target_system=256)
        channel.stop()
