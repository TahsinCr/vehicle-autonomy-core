**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/operations.md)

# Operations, testing and performance

## Shutdown checklist

Prefer structured ownership:

```python
with DependencyContainer() as dependencies:
    with MessageHistory(background=True) as history:
        with MavlinkRuntime(endpoint) as link:
            link.add_history(history)
            ...
```

For async resources use `async with` and `shutdown_async()`. Never call sync
shutdown when a container owns async-only cleanup. If cleanup raises, retain the
owner and retry after correcting the underlying failure.

Mission cleanup failure is intentionally not converted into mission completion.
A mission stays `STOPPING` and keeps resource ownership until `stop()` succeeds.

## Capacity planning

| Area | Limit | Overflow behavior |
|---|---|---|
| Event periodic schedules | `max_schedules` | registration error |
| Replay pending events | `replay_buffer_limit` | affected subscription cancelled and reported |
| Runtime telemetry callbacks | `callback_capacity` / `delivery_capacity` | oldest telemetry callback dropped and counted |
| Runtime lifecycle actions | `callback_action_capacity` / `action_capacity` | fatal delivery error |
| Application dispatcher | `max_pending` | dispatch rejected |
| History writer | `queue_capacity` | explicit recording failure |
| Router latest state | `state_capacity` | LRU eviction |
| Router source condition maps | `source_capacity` | LRU source eviction |
| Vehicle state | `vehicle_state_retention` | disconnected state removed after interval |
| Cache | `per_key_limit`, `max_keys` | oldest item/key evicted |

Do not select capacities solely from message frequency. Include the longest
expected callback/storage stall and a safety margin.

## Observability

- `EventBus.stats`: published, delivered, failed.
- `MavlinkRuntime.state`: lifecycle, connection, peer and router state.
- `MavlinkMessageRouter.stats`: receive/filter/dispatch/loss/state counters.
- `MavlinkRuntime.dropped_callbacks`: callback backpressure.
- `MavlinkRuntime.delivery_error`: fatal callback delivery error.
- `MessageCache.stats`: keys, retained messages, evicted keys.
- `MessageHistory.writer_stats`: submitted, processed, persisted, failed-record,
  queued and batch counters plus the failure flag.
- `MessageHistory.recording_error`: original writer exception.
- `MavlinkApplicationPeer.state`: liveness, RTT and packet counters.
- `MissionEngine.manager_snapshot()`: active/queued/paused missions and resource owners.
- `MissionEngine.query_events()`: structured retained mission events.

Read snapshot properties freely; avoid polling at unnecessarily high frequency.

## SQLite guidance

Use bounded retention for embedded storage unless complete archival is required.
`wal=True` improves writer/read coexistence but creates WAL sidecar files and is
therefore opt-in. `busy_timeout` controls how long SQLite waits for a lock.
Batch size and flush interval trade latency for transaction efficiency.

Always inspect `recording_error` or runtime history errors. A successful MAVLink
receive does not imply a successful persistent write.

## Test commands

Run the complete suite:

```bash
python run_tests.py
```

Equivalent standard discovery:

```bash
python -m unittest discover -v
```

Verify syntax/import compilation:

```bash
python -m compileall -q .
```

The CI matrix runs supported Python versions and builds the wheel. Tests cover
standalone checkout loading and the intended `src/core` submodule layout.

## Benchmarks

```bash
python run_benchmarks.py
```

The benchmark reports wall time, CPU time, retained bytes per operation and peak
temporary allocation. It covers core model serialization, sync/async events,
dependency resolution, MAVLink filtering/cache/routing/application packets and
mission operations.

Benchmark values are comparative, not hard real-time guarantees. Compare the
same interpreter, CPU governor and load. Prefer ratios and distribution trends
over a fixed microsecond threshold from another machine.

## Hardware and integration validation

Before flight or field deployment, add application-owned tests for:

- real serial/UDP reconnect and malformed traffic;
- multiple simultaneous vehicle system IDs;
- sustained expected telemetry rate plus burst margin;
- storage-full and slow-storage behavior;
- callback and mission cleanup failures;
- process shutdown while requests are pending;
- SITL/HIL mission transitions and actuator safety behavior;
- multi-hour soak runs with memory/state counter monitoring.

The core unit suite verifies software contracts; it cannot replace vehicle,
transport and operating-system validation.
