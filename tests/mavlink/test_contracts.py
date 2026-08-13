from __future__ import annotations

import math
import queue
import unittest
from dataclasses import dataclass
from typing import Any

from src.core.mavlink.connection import MavlinkConnection
from src.core.mavlink.endpoint import MavlinkEndpoint
from src.core.mavlink.filter import MavlinkMessageFilter
from src.core.mavlink.remote_log import (
    MavlinkRemoteLogBatch,
    MavlinkRemoteLogLevel,
    MavlinkRemoteLogRecord,
    REMOTE_LOG_MAX_DETAILS_BYTES,
)
from src.core.mavlink.router import MavlinkMessageRouter


class EndpointTests(unittest.TestCase):
    def test_endpoint_normalizes_supported_transport_forms(self) -> None:
        self.assertEqual(MavlinkEndpoint("127.0.0.1:5760").uri, "tcp:127.0.0.1:5760")
        self.assertEqual(MavlinkEndpoint.tcp("localhost", 5760).uri, "tcp:localhost:5760")
        self.assertEqual(MavlinkEndpoint.udp("0.0.0.0", 14550).uri, "udp:0.0.0.0:14550")
        serial = MavlinkEndpoint.serial(" /dev/ttyUSB0 ", baud=57600)
        self.assertEqual((serial.uri, serial.baud), ("/dev/ttyUSB0", 57600))

    def test_endpoint_rejects_invalid_values(self) -> None:
        for uri in ("udp:127.0.0.1:0", "tcp:localhost:65536", "udp:host:not-a-port"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                MavlinkEndpoint(uri)
        with self.assertRaises(ValueError):
            MavlinkEndpoint(source_system=256)
        with self.assertRaises(ValueError):
            MavlinkEndpoint(heartbeat_timeout=0)


class _Header:
    def __init__(self, system: int, component: int, sequence: int = 0) -> None:
        self.srcSystem = system
        self.srcComponent = component
        self.seq = sequence


class _RichMessage:
    def __init__(
        self,
        message_type: str,
        *,
        message_id: int,
        system: int,
        component: int,
        value: int = 0,
        sequence: int = 0,
    ) -> None:
        self._type = message_type
        self._id = message_id
        self._header = _Header(system, component, sequence)
        self.value = value

    def get_type(self) -> str:
        return self._type

    def get_msgId(self) -> int:
        return self._id

    def get_srcSystem(self) -> int:
        return self._header.srcSystem

    def get_srcComponent(self) -> int:
        return self._header.srcComponent

    def get_seq(self) -> int:
        return self._header.seq


class MessageFilterTests(unittest.TestCase):
    def test_composite_filter_matches_all_metadata_and_predicate_fields(self) -> None:
        message = _RichMessage(
            "GLOBAL_POSITION_INT",
            message_id=33,
            system=4,
            component=1,
            value=9,
        )
        message_filter = MavlinkMessageFilter(
            message_types=["heartbeat", "global_position_int"],
            message_ids=[0, 33],
            source_systems=4,
            source_components=(1, 191),
            condition="GLOBAL_POSITION_INT.relative_alt > 0",
            predicate=lambda item: item.value == 9,
        )

        self.assertTrue(message_filter.matches(message, condition_evaluator=lambda _value: True))
        self.assertFalse(message_filter.matches(message, condition_evaluator=lambda _value: False))
        self.assertFalse(
            MavlinkMessageFilter.for_types("HEARTBEAT").matches(message)
        )

    def test_filter_validates_empty_and_out_of_range_criteria(self) -> None:
        with self.assertRaises(ValueError):
            MavlinkMessageFilter(message_types=[])
        with self.assertRaises(ValueError):
            MavlinkMessageFilter(source_systems=256)
        with self.assertRaises(TypeError):
            MavlinkMessageFilter(predicate="not callable")  # type: ignore[arg-type]


class _MavSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def send(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("send", args, kwargs))

    def command_long_send(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("command_long_send", args, kwargs))

    def heartbeat_send(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("heartbeat_send", args, kwargs))


class _RawConnection:
    def __init__(self, heartbeats: list[Any]) -> None:
        self.heartbeats = heartbeats
        self.closed = 0
        self.mav = _MavSender()
        self.target_system = 7
        self.target_component = 1
        self.messages = {"HEARTBEAT": object()}
        self.recv_kwargs: dict[str, Any] | None = None

    def wait_heartbeat(self, *, timeout: float) -> Any:
        del timeout
        return self.heartbeats.pop(0) if self.heartbeats else None

    def probably_vehicle_heartbeat(self, heartbeat: Any) -> bool:
        return heartbeat == "vehicle"

    def recv_match(self, **kwargs: Any) -> str:
        self.recv_kwargs = kwargs
        return "message"

    def set_mode(self, mode: str) -> str:
        return mode

    def close(self) -> None:
        self.closed += 1


class _MavlinkConstants:
    MAV_CMD_SET_MESSAGE_INTERVAL = 511
    MAV_TYPE_GCS = 6
    MAV_AUTOPILOT_INVALID = 8
    MAV_STATE_ACTIVE = 4


class _MavutilStub:
    mavlink = _MavlinkConstants()

    @staticmethod
    def evaluate_condition(condition: str, messages: dict[str, Any]) -> bool:
        return condition == "HEARTBEAT" and "HEARTBEAT" in messages


class ConnectionTests(unittest.TestCase):
    def test_connection_lifecycle_filters_nonvehicle_heartbeat_and_serializes_calls(self) -> None:
        raw = _RawConnection(["companion", "vehicle"])
        connection = MavlinkConnection(
            MavlinkEndpoint(heartbeat_timeout=0.1),
            connection_factory=lambda _endpoint: raw,
            mavutil_module=_MavutilStub(),
        )
        changes: list[bool] = []
        connection.connection_changed.subscribe(changes.append)

        connection.start()
        connection.start()
        self.assertTrue(connection.is_connected)
        self.assertEqual(connection.target_system, 7)
        self.assertTrue(connection.evaluate_condition("HEARTBEAT"))
        self.assertEqual(
            connection.receive(
                message_types=["heartbeat", "global_position_int"],
                condition=" HEARTBEAT ",
                blocking=True,
                timeout=0.5,
            ),
            "message",
        )
        self.assertEqual(
            raw.recv_kwargs,
            {
                "blocking": True,
                "timeout": 0.5,
                "type": ["GLOBAL_POSITION_INT", "HEARTBEAT"],
                "condition": "HEARTBEAT",
            },
        )
        self.assertEqual(connection.request_message_rate(33, 10.0), 100_000)
        self.assertEqual(connection.call_raw("set_mode", "AUTO"), "AUTO")
        self.assertEqual(connection.sent_messages, 2)
        connection.stop()
        connection.stop()

        self.assertEqual(changes, [True, False])
        self.assertEqual(raw.closed, 1)

    def test_connect_failure_closes_partial_transport_and_publishes_error(self) -> None:
        raw = _RawConnection([])
        connection = MavlinkConnection(
            MavlinkEndpoint(heartbeat_timeout=0.01),
            connection_factory=lambda _endpoint: raw,
        )
        errors: list[Exception] = []
        connection.errors.subscribe(errors.append)

        with self.assertRaises(TimeoutError):
            connection.start()

        self.assertFalse(connection.is_connected)
        self.assertEqual(raw.closed, 1)
        self.assertIsInstance(errors[-1], TimeoutError)

    def test_invalid_send_method_is_reported(self) -> None:
        raw = _RawConnection(["vehicle"])
        connection = MavlinkConnection(
            MavlinkEndpoint(heartbeat_timeout=0.1),
            connection_factory=lambda _endpoint: raw,
        )
        errors: list[Exception] = []
        connection.errors.subscribe(errors.append)
        connection.start()

        with self.assertRaises(ValueError):
            connection.call_mav("missing_send")

        self.assertIsInstance(errors[-1], ValueError)
        connection.stop()


class _RouterConnection:
    def __init__(self) -> None:
        self.inbox: queue.Queue[_RichMessage] = queue.Queue()
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def receive(self, *, blocking: bool, timeout: float | None) -> Any:
        del blocking
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def evaluate_condition(self, condition: str) -> bool:
        return condition == "ready"


class RouterContractTests(unittest.TestCase):
    def test_router_filters_history_latest_and_wait_timeout(self) -> None:
        connection = _RouterConnection()
        router = MavlinkMessageRouter(
            connection,  # type: ignore[arg-type]
            poll_timeout=0.01,
            stop_timeout=0.2,
        )
        received: list[int] = []
        router.subscribe(
            lambda message: received.append(message.value),
            MavlinkMessageFilter(
                message_types="HEARTBEAT",
                source_systems=3,
                condition="ready",
            ),
        )
        router.start()
        connection.inbox.put(
            _RichMessage("HEARTBEAT", message_id=0, system=2, component=1, value=1)
        )
        connection.inbox.put(
            _RichMessage("HEARTBEAT", message_id=0, system=3, component=1, value=2)
        )
        matched = router.wait_for(
            MavlinkMessageFilter(message_types="HEARTBEAT", source_systems=3),
            timeout=1.0,
        )

        self.assertEqual(matched.value, 2)
        self.assertEqual(received, [2])
        self.assertEqual(router.latest("HEARTBEAT").value, 2)
        self.assertEqual(len(router.history("HEARTBEAT")), 2)
        with self.assertRaises(TimeoutError):
            router.wait_for("ATTITUDE", timeout=0.02)
        router.stop()


class RemoteLogTests(unittest.TestCase):
    def _record(self, sequence: int = 1, **changes: Any) -> MavlinkRemoteLogRecord:
        values = {
            "sequence": sequence,
            "source": "mission",
            "action": "started",
            "message": "Mission started",
            **changes,
        }
        return MavlinkRemoteLogRecord(**values)

    def test_remote_log_is_domain_only_detached_and_round_trips(self) -> None:
        details = {"nested": {"values": [1]}}
        record = self._record(details=details, level=MavlinkRemoteLogLevel.ERROR)
        details["nested"]["values"].append(2)  # type: ignore[index,union-attr]

        self.assertFalse(hasattr(record.level, "yki_severity"))
        self.assertEqual(record.level.priority, 40)
        self.assertEqual(record.to_payload()["details"], {"nested": {"values": [1]}})
        with self.assertRaises(TypeError):
            record.details["new"] = True  # type: ignore[index]
        with self.assertRaises(AttributeError):
            record.details["nested"]["values"].append(2)  # type: ignore[union-attr]
        copied = self._record(2, details=record.details)
        self.assertEqual(copied.to_payload()["details"], record.to_payload()["details"])
        batch = MavlinkRemoteLogBatch("session-001", (record, copied))
        restored = MavlinkRemoteLogBatch.from_payload(batch.to_payload())
        self.assertEqual(restored.to_payload(), batch.to_payload())

    def test_remote_log_validates_details_order_and_version(self) -> None:
        with self.assertRaises(ValueError):
            self._record(details={"value": math.nan})
        with self.assertRaises(ValueError):
            self._record(details={"text": "x" * REMOTE_LOG_MAX_DETAILS_BYTES})
        with self.assertRaises(ValueError):
            MavlinkRemoteLogBatch("session-001", (self._record(2), self._record(1)))
        with self.assertRaisesRegex(ValueError, "protocol version"):
            MavlinkRemoteLogBatch.from_payload(
                {"version": 99, "session": "session-001", "records": []}
            )


if __name__ == "__main__":
    unittest.main()
