"""Optional, source-filtered message history with interchangeable storage."""

from __future__ import annotations

import json
import sqlite3
import threading
import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import islice
from os import PathLike
from types import TracebackType
from typing import TypeAlias, TypeVar

from .message import MavlinkMessageEnvelope
from .recording import HistoryWriter, HistoryWriterStats

JsonValue: TypeAlias = "None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]"
_Row: TypeAlias = tuple[int, int | None, int | None, str, float, str]
_History = TypeVar("_History", bound="MessageHistory")


def _normalize_json_value(value: object) -> JsonValue:
    """Return strict JSON data while preserving MAVLink unknown values as null."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    # Keep unsupported values intact long enough for json.dumps() to report
    # its normal, useful TypeError rather than hiding malformed serializers.
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """Portable message snapshot; received_at is Unix time, not monotonic time."""

    sequence: int
    system_id: int | None
    component_id: int | None
    message_type: str
    received_at: float
    payload: JsonValue


class MessageHistory:
    """Thread-safe memory history. Limit is total records; None is unbounded.

    Query results are detached JSON snapshots, oldest first. Subclasses can
    replace append/query/clear/close without changing runtime registration.
    """

    def __init__(
        self,
        *,
        limit: int | None = 1000,
        background: bool = False,
        queue_capacity: int = 1024,
        batch_size: int = 64,
        flush_interval: float = 0.02,
    ) -> None:
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise ValueError("History limit must be a positive integer or None")
        self.limit = limit
        self._lock = threading.RLock()
        self._closed = False
        self._records: deque[_Row] = deque(maxlen=limit)
        self._writer = (
            HistoryWriter(
                self._append_batch,
                queue_capacity,
                batch_size=batch_size,
                flush_interval=flush_interval,
            )
            if background
            else None
        )

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Message history is closed")

    @staticmethod
    def _encode(envelope: MavlinkMessageEnvelope) -> str:
        serializer = getattr(envelope.message, "to_dict", None)
        if not callable(serializer):
            raise TypeError("History messages must provide to_dict()")
        return json.dumps(_normalize_json_value(serializer()), allow_nan=False)

    def append(self, envelope: MavlinkMessageEnvelope) -> None:
        if self._writer is not None:
            self._writer.submit(envelope)
            return
        self._append_batch((envelope,))

    def _append_batch(
        self,
        envelopes: tuple[MavlinkMessageEnvelope, ...],
    ) -> None:
        rows = tuple(
            (
                envelope.sequence,
                envelope.source_system,
                envelope.source_component,
                envelope.message_type,
                envelope.received_at,
                self._encode(envelope),
            )
            for envelope in envelopes
        )
        with self._lock:
            self._check_open()
            self._records.extend(rows)

    @property
    def recording_error(self) -> Exception | None:
        return None if self._writer is None else self._writer.failure

    @property
    def writer_stats(self) -> HistoryWriterStats | None:
        """Return a stable writer snapshot, or None for synchronous history."""

        return None if self._writer is None else self._writer.stats

    def flush(self, timeout: float = 5.0) -> None:
        if self._writer is not None:
            self._writer.flush(timeout)

    def query(self, *, system_id: int | None = None, component_id: int | None = None,
              message_type: str | None = None, since: float | None = None,
              until: float | None = None, limit: int | None = None) -> tuple[MessageRecord, ...]:
        """Filter by source/type and inclusive Unix timestamps; limit selects the tail."""
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise ValueError("Query limit must be a positive integer or None")
        for identifier in (system_id, component_id):
            if identifier is not None and (isinstance(identifier, bool) or not isinstance(identifier, int)
                                           or not 0 <= identifier <= 255):
                raise ValueError("Source IDs must be integers from 0 to 255")
        for timestamp in (since, until):
            if timestamp is not None and not math.isfinite(timestamp):
                raise ValueError("Query timestamps must be finite")
        if since is not None and until is not None and since > until:
            raise ValueError("since must not exceed until")
        message_type = message_type.strip().upper() if message_type is not None else None
        if message_type == "":
            raise ValueError("Message type must not be empty")
        self.flush()
        with self._lock:
            self._check_open()
            rows = self._select(system_id, component_id, message_type, since, until, limit)
        return tuple(MessageRecord(*row[:-1], json.loads(row[-1])) for row in rows)

    def _select(self, system: int | None, component: int | None, kind: str | None,
                since: float | None, until: float | None, limit: int | None) -> list[_Row]:
        # Scan newest-first so latest/tail queries stop as soon as satisfied.
        matches = (row for row in reversed(self._records)
                if (system is None or row[1] == system)
                and (component is None or row[2] == component)
                and (kind is None or row[3] == kind)
                and (since is None or row[4] >= since)
                and (until is None or row[4] <= until))
        rows = list(islice(matches, limit)) if limit is not None else list(matches)
        rows.reverse()
        return rows

    def latest(self, *, system_id: int | None = None, component_id: int | None = None,
               message_type: str | None = None, since: float | None = None,
               until: float | None = None) -> MessageRecord | None:
        rows = self.query(system_id=system_id, component_id=component_id,
                          message_type=message_type, since=since, until=until, limit=1)
        return rows[0] if rows else None

    def clear(self) -> None:
        self.flush()
        with self._lock:
            self._check_open()
            self._records.clear()

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
        with self._lock:
            self._closed = True

    def __enter__(self: _History) -> _History:
        self._check_open()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        self.close()


class SqliteMessageHistory(MessageHistory):
    """Persistent JSON history using a bounded background SQLite writer.

    No pickle or pymavlink dialect is needed to read saved records. A retention
    limit applies to the whole database, including records from previous runs.
    """

    def __init__(self, path: str | PathLike[str], *, limit: int | None = 1000,
                 queue_capacity: int = 1024, batch_size: int = 64,
                 flush_interval: float = 0.02, wal: bool = False,
                 busy_timeout: float = 5.0) -> None:
        if not isinstance(wal, bool):
            raise TypeError("wal must be a boolean")
        if (isinstance(busy_timeout, bool) or not isinstance(busy_timeout, (int, float))
                or not math.isfinite(busy_timeout) or busy_timeout < 0):
            raise ValueError("busy_timeout must be finite and non-negative")
        super().__init__(limit=limit)
        self._database = sqlite3.connect(
            path,
            check_same_thread=False,
            timeout=float(busy_timeout),
        )
        try:
            if wal:
                self._database.execute("PRAGMA journal_mode=WAL")
            with self._database:
                self._database.execute("""CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, sequence INTEGER, system_id INTEGER,
                    component_id INTEGER, message_type TEXT, received_at REAL, payload TEXT)""")
                self._database.execute("CREATE INDEX IF NOT EXISTS messages_source ON messages(system_id, component_id, message_type, id)")
                self._trim()
            self._writer = HistoryWriter(
                self._write_batch,
                queue_capacity,
                batch_size=batch_size,
                flush_interval=flush_interval,
            )
        except BaseException:
            self._database.close()
            raise

    def _trim(self) -> None:
        if self.limit is not None:
            self._database.execute("DELETE FROM messages WHERE id <= (SELECT id FROM messages ORDER BY id DESC LIMIT 1 OFFSET ?)", (self.limit,))

    def append(self, envelope: MavlinkMessageEnvelope) -> None:
        self._writer.submit(envelope)

    def query(self, *, system_id: int | None = None, component_id: int | None = None,
              message_type: str | None = None, since: float | None = None,
              until: float | None = None, limit: int | None = None) -> tuple[MessageRecord, ...]:
        self.flush()
        return super().query(system_id=system_id, component_id=component_id,
                             message_type=message_type, since=since, until=until, limit=limit)

    def _write_batch(self, envelopes: tuple[MavlinkMessageEnvelope, ...]) -> None:
        rows = tuple(
            (
                envelope.sequence,
                envelope.source_system,
                envelope.source_component,
                envelope.message_type,
                envelope.received_at,
                self._encode(envelope),
            )
            for envelope in envelopes
        )
        with self._lock:
            self._check_open()
            with self._database:
                self._database.executemany(
                    "INSERT INTO messages(sequence, system_id, component_id, message_type, received_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                self._trim()

    def _select(self, system: int | None, component: int | None, kind: str | None,
                since: float | None, until: float | None, limit: int | None) -> list[_Row]:
        clauses: list[str] = []
        values: list[int | float | str] = []
        for column, operator, value in (("system_id", "=", system), ("component_id", "=", component),
                                         ("message_type", "=", kind), ("received_at", ">=", since),
                                         ("received_at", "<=", until)):
            if value is not None:
                clauses.append(f"{column} {operator} ?")
                values.append(value)
        query = "SELECT sequence, system_id, component_id, message_type, received_at, payload FROM messages"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC"
        if limit is not None:
            query += " LIMIT ?"
            values.append(limit)
        return list(reversed(self._database.execute(query, values).fetchall()))

    def clear(self) -> None:
        self.flush()
        with self._lock:
            self._check_open()
            with self._database:
                self._database.execute("DELETE FROM messages")

    def close(self) -> None:
        error = None
        try:
            self._writer.close()
        except Exception as failure:
            if self._writer._thread.is_alive():
                raise
            error = failure
        with self._lock:
            if not self._closed:
                self._database.close()
                self._closed = True
        if error is not None:
            raise error
