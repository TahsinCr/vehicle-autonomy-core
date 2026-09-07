from __future__ import annotations

import tempfile
import unittest
import threading
from pathlib import Path

from src.core.mavlink import MessageHistory, SqliteMessageHistory, MavlinkMessageEnvelope, MavlinkRuntime, AsyncMavlinkRuntime, MavlinkMessageRouter, MavlinkMessageFilter
from .test_runtime import FakeClient, WireMessage, emit
from .test_contracts import _RouterConnection, _RichMessage


class RecordedMessage(WireMessage):
    def to_dict(self):
        return {"value": [self.system]}


def envelope(sequence, system=12, component=1, kind="ATTITUDE"):
    return MavlinkMessageEnvelope.wrap(sequence, RecordedMessage(system, component, kind))


class MessageHistoryTests(unittest.TestCase):
    def test_slow_sql_writer_does_not_block_append_and_reports_overflow(self):
        entered, release = threading.Event(), threading.Event()
        class SlowHistory(SqliteMessageHistory):
            def _write(self, row):
                entered.set()
                release.wait(2)
                super()._write(row)
        with tempfile.TemporaryDirectory() as directory:
            history = SlowHistory(Path(directory) / "slow.db", queue_capacity=1)
            try:
                history.append(envelope(1))
                self.assertTrue(entered.wait(1))
                history.append(envelope(2))
                with self.assertRaises(BufferError):
                    history.append(envelope(3))
                self.assertIsInstance(history.recording_error, BufferError)
            finally:
                release.set()
                with self.assertRaises(RuntimeError):
                    history.close()
            with SqliteMessageHistory(Path(directory) / "slow.db") as reopened:
                self.assertEqual([row.sequence for row in reopened.query()], [1, 2])

    def test_background_write_failure_is_visible_on_flush_and_close(self):
        class BrokenHistory(SqliteMessageHistory):
            def _write(self, row):
                raise OSError("disk failed")
        with tempfile.TemporaryDirectory() as directory:
            history = BrokenHistory(Path(directory) / "broken.db")
            history.append(envelope(1))
            with self.assertRaises(RuntimeError):
                history.flush()
            self.assertIsInstance(history.recording_error, OSError)
            with self.assertRaises(RuntimeError):
                history.close()
    def test_tail_query_stops_after_enough_matches(self):
        from collections import deque

        class CountingRows(deque):
            visited = 0

            def __reversed__(self):
                for row in super().__reversed__():
                    self.visited += 1
                    yield row

        history = MessageHistory(limit=None)
        for index in range(100):
            history.append(envelope(index, system=12 + index % 2))
        history._records = CountingRows(history._records)
        rows = history.query(system_id=13, limit=2)
        self.assertEqual([row.sequence for row in rows], [97, 99])
        self.assertEqual(history._records.visited, 3)

    def test_filter_validation_and_backend_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            with MessageHistory(limit=None) as memory, SqliteMessageHistory(Path(directory) / "filters.db", limit=None) as sql:
                for index in range(12):
                    item = envelope(index, system=12 + index % 2, component=1 + index % 3)
                    memory.append(item)
                    sql.append(item)
                filters = ({}, {"system_id": 13, "limit": 2}, {"component_id": 2},
                           {"message_type": " attitude ", "limit": 3}, {"system_id": 99})
                for query in filters:
                    self.assertEqual([r.sequence for r in memory.query(**query)],
                                     [r.sequence for r in sql.query(**query)])
                invalid = ({"system_id": True}, {"component_id": 256}, {"message_type": " "},
                           {"since": float("nan")}, {"until": float("inf")}, {"since": 2, "until": 1})
                for storage in (memory, sql):
                    for query in invalid:
                        with self.assertRaises(ValueError):
                            storage.query(**query)

    def test_router_latest_keeps_each_source_after_history_eviction(self):
        connection = _RouterConnection()
        router = MavlinkMessageRouter(connection, history_limit=1, poll_timeout=0.01)
        router.start()
        try:
            connection.inbox.put(_RichMessage("HEARTBEAT", message_id=0, system=12, component=1, value=1))
            router.wait_for("HEARTBEAT", timeout=1)
            connection.inbox.put(_RichMessage("ATTITUDE", message_id=30, system=13, component=1, value=2))
            router.wait_for("ATTITUDE", timeout=1)
            self.assertEqual(router.history("HEARTBEAT"), ())
            self.assertEqual(router.latest(MavlinkMessageFilter(message_types="HEARTBEAT", source_systems=12)).value, 1)
        finally:
            router.stop()

    def test_history_failure_is_reported_by_runtime(self):
        class BrokenHistory(MessageHistory):
            def append(self, envelope):
                raise OSError("Storage failed")
        client = FakeClient([])
        with MavlinkRuntime(client=client) as runtime:
            errors = []
            runtime.errors.subscribe(errors.append)
            runtime.add_history(BrokenHistory())
            client.router.envelopes.publish(envelope(1))
            self.assertEqual(errors[-1].source, "history")
            self.assertIsInstance(errors[-1].error, OSError)

    def test_memory_and_sqlite_share_query_and_retention_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            for history in (MessageHistory(limit=2), SqliteMessageHistory(Path(directory) / "history.db", limit=2)):
                with self.subTest(storage=type(history).__name__), history:
                    for index in range(3):
                        history.append(envelope(index, system=12 + index))
                    self.assertEqual([row.sequence for row in history.query()], [1, 2])
                    self.assertEqual(history.latest(system_id=13).sequence, 1)
                    self.assertIsNone(history.latest(component_id=42))
                    self.assertEqual(len(history.query(message_type="attitude", limit=1)), 1)
                    record = history.latest()
                    self.assertEqual(len(history.query(since=record.received_at)), 1)
                    self.assertEqual(len(history.query(until=record.received_at)), 2)
                    record.payload["value"].append(99)
                    self.assertEqual(history.latest().payload["value"], [14])
                    history.clear()
                    self.assertEqual(history.query(), ())
                with self.assertRaises(RuntimeError):
                    history.query()

    def test_sqlite_reopen_and_unlimited_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.db"
            with SqliteMessageHistory(path, limit=None) as history:
                for index in range(10):
                    history.append(envelope(index))
            with SqliteMessageHistory(path, limit=None) as history:
                self.assertEqual(len(history.query()), 10)
            with SqliteMessageHistory(path, limit=2) as history:
                self.assertEqual([row.sequence for row in history.query()], [8, 9])

    def test_runtime_attach_detach_and_storage_ownership(self):
        client = FakeClient([])
        history = MessageHistory(limit=None)
        with MavlinkRuntime(client=client) as runtime:
            subscription = runtime.add_history(history)
            with self.assertRaises(ValueError):
                runtime.add_history(history)
            client.router.envelopes.publish(envelope(1))
            self.assertEqual(history.latest().sequence, 1)
            subscription.cancel()
            client.router.envelopes.publish(envelope(2))
            self.assertEqual(history.latest().sequence, 1)
            attached = runtime.add_history(history)
        self.assertFalse(attached.active)
        self.assertEqual(len(history.query()), 1)
        history.close()

    def test_latest_survives_history_eviction(self):
        client = FakeClient([])
        with MavlinkRuntime(client=client, vehicle_history=1) as runtime:
            emit(client, 12, 1)
            vehicle = runtime.vehicles.get(12)
            heartbeat = vehicle.latest("HEARTBEAT")
            emit(client, 12, 1, "ATTITUDE")
            self.assertIs(vehicle.latest("HEARTBEAT"), heartbeat)
            self.assertIs(vehicle.get_component(1).latest("HEARTBEAT"), heartbeat)

    def test_invalid_limits(self):
        for limit in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                MessageHistory(limit=limit)


class AsyncHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_attach_after_start(self):
        history = MessageHistory()
        client = FakeClient([])
        async with AsyncMavlinkRuntime(client=client) as runtime:
            subscription = runtime.add_history(history)
            client.router.envelopes.publish(envelope(1))
            self.assertEqual(history.latest().sequence, 1)
        self.assertFalse(subscription.active)
        history.close()
