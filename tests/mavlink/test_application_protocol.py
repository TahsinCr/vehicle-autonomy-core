from __future__ import annotations

import math
import time
import unittest
from collections.abc import Mapping

from src.core.mavlink import application as application_module
from src.core.mavlink.application import (
    MavlinkApplicationAssembler,
    MavlinkApplicationCodec,
    MavlinkApplicationPacket,
    MavlinkApplicationProtocolError,
)
from src.core.mavlink.dispatch import MavlinkApplicationResult


class ApplicationPacketTests(unittest.TestCase):
    def test_payload_is_detached_and_serializes_to_a_copy(self) -> None:
        original = {"nested": {"values": [1, 2]}}
        packet = MavlinkApplicationPacket("Camera.Capture", original)
        original["nested"]["values"].append(3)  # type: ignore[index,union-attr]

        self.assertEqual(packet.packet_type, "camera.capture")
        self.assertIsInstance(packet.payload, Mapping)
        self.assertEqual(packet.to_dict()["payload"], {"nested": {"values": [1, 2]}})
        serialized = packet.to_dict()
        serialized["payload"]["nested"]["values"].append(4)
        self.assertEqual(packet.to_dict()["payload"], {"nested": {"values": [1, 2]}})
        with self.assertRaises(TypeError):
            packet.payload["new"] = True  # type: ignore[index]
        with self.assertRaises(AttributeError):
            packet.payload["nested"]["values"].append(4)  # type: ignore[union-attr]
        copied = MavlinkApplicationPacket("copy", packet.payload)
        self.assertEqual(copied.to_dict()["payload"], packet.to_dict()["payload"])

    def test_application_result_payload_is_detached(self) -> None:
        original = {"nested": {"accepted": True}}
        result = MavlinkApplicationResult.success(original)
        original["nested"]["accepted"] = False

        self.assertTrue(result.payload["nested"]["accepted"])
        with self.assertRaises(TypeError):
            result.payload["nested"] = {}  # type: ignore[index]

    def test_packet_validates_time_sources_type_and_json_payload(self) -> None:
        for sent_at in (0.0, -1.0, math.nan, math.inf, -math.inf):
            with self.subTest(sent_at=sent_at), self.assertRaises(ValueError):
                MavlinkApplicationPacket("status", sent_at=sent_at)

        for source in (-1, 256):
            with self.subTest(source_system=source), self.assertRaises(ValueError):
                MavlinkApplicationPacket("status", source_system=source)
            with self.subTest(source_component=source), self.assertRaises(ValueError):
                MavlinkApplicationPacket("status", source_component=source)

        with self.assertRaises(ValueError):
            MavlinkApplicationPacket("x" * 97)
        with self.assertRaises(ValueError):
            MavlinkApplicationPacket("status", payload={"value": math.nan})
        with self.assertRaises(ValueError):
            MavlinkApplicationPacket("status", payload={"value": object()})


class ApplicationCodecTests(unittest.TestCase):
    def test_single_fragment_round_trip(self) -> None:
        packet = MavlinkApplicationPacket("status.update", {"ready": True}, packet_id=7)
        fragments = MavlinkApplicationCodec.encode(packet)

        self.assertEqual(len(fragments), 1)
        decoded = MavlinkApplicationAssembler().accept(
            fragments[0], source_system=4, source_component=191
        )
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.packet_id, 7)
        self.assertEqual(decoded.payload, {"ready": True})
        self.assertEqual(decoded.source_system, 4)
        self.assertEqual(decoded.source_component, 191)

    def test_multiple_out_of_order_fragments_round_trip(self) -> None:
        packet = MavlinkApplicationPacket("data.large", {"text": "x" * 2_000})
        fragments = MavlinkApplicationCodec.encode(packet)
        assembler = MavlinkApplicationAssembler()
        decoded = None

        for fragment in reversed(fragments):
            decoded = assembler.accept(fragment)

        self.assertGreater(len(fragments), 1)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.payload["text"], "x" * 2_000)

    def test_identical_duplicate_fragment_is_idempotent(self) -> None:
        packet = MavlinkApplicationPacket("data.large", {"text": "x" * 1_000})
        fragments = MavlinkApplicationCodec.encode(packet)
        assembler = MavlinkApplicationAssembler()

        self.assertIsNone(assembler.accept(fragments[0]))
        self.assertIsNone(assembler.accept(fragments[0]))
        decoded = None
        for fragment in fragments[1:]:
            decoded = assembler.accept(fragment)

        self.assertIsNotNone(decoded)
        self.assertIsNone(assembler.accept(fragments[-1]))

    def test_conflicting_duplicate_fragment_is_rejected(self) -> None:
        packet = MavlinkApplicationPacket("data.large", {"text": "x" * 1_000})
        first = MavlinkApplicationCodec.encode(packet)[0]
        conflicting = bytearray(first)
        conflicting[-1] ^= 0x01
        assembler = MavlinkApplicationAssembler()
        assembler.accept(first)

        with self.assertRaisesRegex(MavlinkApplicationProtocolError, "Tekrarlanan"):
            assembler.accept(conflicting)

    def test_crc_mismatch_is_rejected(self) -> None:
        packet = MavlinkApplicationPacket("status", {"ready": True})
        corrupted = bytearray(MavlinkApplicationCodec.encode(packet)[0])
        corrupted[-1] ^= 0x01

        with self.assertRaisesRegex(MavlinkApplicationProtocolError, "CRC"):
            MavlinkApplicationAssembler().accept(corrupted)

    def test_fragment_timeout_discards_incomplete_assembly(self) -> None:
        packet = MavlinkApplicationPacket("data.large", {"text": "x" * 1_000})
        fragments = MavlinkApplicationCodec.encode(packet)
        assembler = MavlinkApplicationAssembler(fragment_timeout=0.01)
        assembler.accept(fragments[0])
        key = (0, 0, packet.packet_id)
        first_created = assembler._assemblies[key].created_monotonic

        time.sleep(0.02)
        self.assertIsNone(assembler.accept(fragments[1]))

        self.assertGreater(assembler._assemblies[key].created_monotonic, first_created)
        self.assertNotIn(0, assembler._assemblies[key].fragments)

    def test_maximum_encoded_packet_boundary(self) -> None:
        low = 0
        high = MavlinkApplicationCodec.max_packet_bytes * 2
        while low + 1 < high:
            middle = (low + high) // 2
            packet = MavlinkApplicationPacket(
                "data",
                {"text": "x" * middle},
                packet_id=1,
                sent_at=1.0,
            )
            try:
                MavlinkApplicationCodec.encode(packet)
            except MavlinkApplicationProtocolError:
                high = middle
            else:
                low = middle

        accepted = MavlinkApplicationPacket(
            "data", {"text": "x" * low}, packet_id=1, sent_at=1.0
        )
        rejected = MavlinkApplicationPacket(
            "data", {"text": "x" * high}, packet_id=1, sent_at=1.0
        )
        self.assertLessEqual(
            len(MavlinkApplicationCodec.encode(accepted)),
            72,
        )
        with self.assertRaisesRegex(MavlinkApplicationProtocolError, "çok büyük"):
            MavlinkApplicationCodec.encode(rejected)

    def test_malformed_json_and_nonfinite_constant_are_rejected(self) -> None:
        with self.assertRaises(MavlinkApplicationProtocolError):
            MavlinkApplicationCodec.decode_packet(1, b"{")
        with self.assertRaises(MavlinkApplicationProtocolError):
            MavlinkApplicationCodec.decode_packet(
                1,
                b'{"type":"status","payload":{"value":NaN},"sent_at":1}',
            )

    def test_unsupported_protocol_version_is_rejected(self) -> None:
        packet = MavlinkApplicationPacket("status")
        fragment = bytearray(MavlinkApplicationCodec.encode(packet)[0])
        fragment[2] = application_module._VERSION + 1

        with self.assertRaisesRegex(MavlinkApplicationProtocolError, "sürümü"):
            MavlinkApplicationCodec.decode_fragment(fragment)

    def test_inflight_assembly_count_is_bounded(self) -> None:
        assembler = MavlinkApplicationAssembler(max_inflight_assemblies=2)
        fragments = [
            MavlinkApplicationCodec.encode(
                MavlinkApplicationPacket(
                    "data.large",
                    {"text": "x" * 1_000},
                    packet_id=packet_id,
                )
            )[0]
            for packet_id in (1, 2, 3)
        ]

        self.assertIsNone(assembler.accept(fragments[0]))
        self.assertIsNone(assembler.accept(fragments[1]))
        with self.assertRaisesRegex(MavlinkApplicationProtocolError, "Çok fazla"):
            assembler.accept(fragments[2])

    def test_inflight_fragment_bytes_are_bounded(self) -> None:
        fragment = MavlinkApplicationCodec.encode(
            MavlinkApplicationPacket("data.large", {"text": "x" * 1_000})
        )[0]
        assembler = MavlinkApplicationAssembler(max_inflight_bytes=8)

        with self.assertRaisesRegex(MavlinkApplicationProtocolError, "byte sınırını"):
            assembler.accept(fragment)

    def test_completed_packet_history_is_bounded(self) -> None:
        assembler = MavlinkApplicationAssembler(max_completed_packets=2)
        fragments = [
            MavlinkApplicationCodec.encode(
                MavlinkApplicationPacket("status", packet_id=packet_id)
            )[0]
            for packet_id in (1, 2, 3)
        ]

        for fragment in fragments:
            self.assertIsNotNone(assembler.accept(fragment))

        self.assertEqual(len(assembler._completed), 2)
        self.assertNotIn((0, 0, 1), assembler._completed)


if __name__ == "__main__":
    unittest.main()
