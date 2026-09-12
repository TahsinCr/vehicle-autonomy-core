**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/mavlink.md)

# MAVLink

The MAVLink package has four levels:

1. `MavlinkConnection` owns the pymavlink connection.
2. `MavlinkMessageRouter` is the single reader and routes received messages.
3. `MavlinkClient` combines connection and router operations.
4. `MavlinkRuntime` adds callbacks, vehicle discovery, history and application packets.

Most applications should start with a runtime. Lower levels remain public for
custom transport composition.

## Endpoints

```text
MavlinkEndpoint(
    uri="udp:127.0.0.1:14550",
    baud=115200,
    source_system=255,
    source_component=0,
    dialect="ardupilotmega",
    autoreconnect=True,
    heartbeat_timeout=10.0,
)
```

Factories:

```python
MavlinkEndpoint.udp("0.0.0.0", 14550, source_system=245)
MavlinkEndpoint.tcp("127.0.0.1", 5760)
MavlinkEndpoint.serial("/dev/ttyACM0", baud=921600)
```

`normalize_uri(uri)` validates/normalizes an address. `connection_kwargs()`
returns the arguments used to create the pymavlink connection. Ports and source
IDs reject booleans and out-of-range integers.

## Connection

```text
MavlinkConnection(endpoint, *, connection_factory=None, mavutil_module=None)
```

| Method | Parameters | Purpose |
|---|---|---|
| `connect()` / `start()` | none | Open connection |
| `stop()` / `close()` | none | Close connection |
| `reconnect()` | none | Full close/open cycle |
| `receive()` | `message_types`, `condition`, `blocking`, `timeout` | Read one message |
| `send(message)` | pymavlink message | Send encoded message |
| `send_named(name, **parameters)` | MAVLink sender method suffix | Build and send |
| `request_message_rate(message_id, frequency_hz, target_system=None, target_component=None)` | rate request | Return interval in microseconds |
| `call_mav(name, *args, **kwargs)` | dialect sender call | Call connection `.mav` method |
| `call_raw(name, *args, **kwargs)` | raw connection call | Advanced escape hatch |
| `evaluate_condition(condition)` | pymavlink expression | Evaluate global connection state |
| `evaluate_condition_for_state(condition, message_state)` | expression and source-local map | Evaluate isolated source state |

`connection_factory` and `mavutil_module` support alternate transports and
testing. `MavlinkUnavailableError` is raised when pymavlink is required but not installed.
`sent_messages` counts successful sends during the current connection lifecycle.

## Router

```text
MavlinkMessageRouter(
    connection,
    history_limit=512,
    cache_per_type=64,
    poll_timeout=0.25,
    error_backoff=0.1,
    stop_timeout=2.0,
    state_capacity=None,
    source_capacity=None,
)
```

The router owns exactly one receive thread. `state_capacity` bounds latest
source/component/type entries; `source_capacity` bounds source-local condition
maps. Both use LRU eviction and default to unbounded for compatibility.

Methods:

- `start()`, `stop()`, `close()`;
- `subscribe(callback, message_filter=None) -> Subscription`;
- `latest(message_filter=None) -> message | None`;
- `history(message_filter=None, limit=None) -> tuple[Envelope, ...]`;
- `wait_for(message_types, predicate=None, timeout=3.0, after_sequence=None)`;
- `add_filter(predicate) -> Subscription`.

Ingress filters receive a `MavlinkMessageEnvelope`, run in registration order on
the receive thread, and may be added directly or as decorators:

```python
@router.add_filter
def keep_known_network(envelope):
    return envelope.source_system in allowed_systems
```

Keep ingress filters fast. Returning false drops the message before history,
cache, vehicle discovery and subscriber dispatch.

`MavlinkRouterStats` fields: `running`, `sequence`, `received_messages`,
`receive_errors`, `dispatch_errors`, `estimated_dropped_messages`,
`delivery_quality`, `started_monotonic`, `last_message_monotonic`,
`filtered_messages`, `state_evictions`, `cached_state_keys`.
Errors are published as `MavlinkRouterError(phase, error, envelope)`.

## Message filtering

```python
MavlinkMessageFilter(
    message_types={"HEARTBEAT", "ATTITUDE"},
    source_systems={12},
    source_components={1},
    message_ids=None,
    condition=None,
    predicate=None,
)
```

`for_types(*message_types, **criteria)` is a convenience factory. `matches()`
accepts an optional condition evaluator and envelope metadata.

Native `condition=` is causal only for live router subscription. Historical
`latest()`, `history()` and `wait_for()` reject it because current state cannot
truthfully reconstruct an earlier condition; use a Python `predicate` there.

`MavlinkMessageEnvelope` carries `sequence`, raw `message`, normalized
`message_type`, source IDs, message ID, monotonic receive time and Unix receive
time. `wrap(sequence, message)` captures metadata; `to_dict(include_payload=False)`
creates a detached representation.

`MavlinkHeader` and `MavlinkMessage` are structural typing protocols for
pymavlink-compatible objects.

## Client

```text
MavlinkClient(endpoint=None, *, connection=None, router=None, router_options=None)
```

The client exposes router `subscribe`, `wait_for`, `latest`, connection
`send`, `send_named`, `request_message_rate`, `call_mav`, `call_raw`, endpoint
reconfiguration and service lifecycle. Do not pass `router_options` with an
already-created router.
`configure_endpoint(endpoint)` is allowed only while stopped.

## Synchronous runtime

```text
MavlinkRuntime(
    endpoint=None,
    *,
    client=None,
    router_options=None,
    application_role=None,
    channel=None,
    peer=None,
    dispatcher=None,
    workers=1,
    max_pending=64,
    channel_options=None,
    peer_options=None,
    heartbeat_timeout=5.0,
    vehicle_history=128,
    vehicle_state_retention=None,
    callback_capacity=1024,
    callback_action_capacity=1024,
)
```

`_delivery` is internal and must not be supplied by applications.

```python
with MavlinkRuntime(endpoint) as link:
    @link.subscribe("ATTITUDE", frequency_hz=20.0)
    def attitude(message):
        ...

    @link.on_error
    def runtime_error(action):
        ...

    latest = link.latest(MavlinkMessageFilter.for_types("HEARTBEAT"))
```

Public operations:

- lifecycle: `start`, `stop`, `close`, `reconnect`, `running`, `state`;
- messages: `subscribe`, `once`, `wait_for`, `latest`, `send`, `send_named`;
- actions: `on`, `on_start`, `on_stop`, `on_connected`, `on_disconnected`, `on_error`;
- storage/filtering: `add_history`, `add_filter`, `prune_vehicles`;
- app protocol: `handle`, `notify`, `request`, `application_enabled`;
- monitoring: `delivery_error`, `dropped_callbacks`, `errors`, `router`.

Callback `**options` are the policies documented for `CallbackSubscription`:
`max_calls`, `frequency_hz`, `timeout`, `predicate`, `enabled` and hooks.

`MavlinkRuntimeState` contains `running`, `connected`, `application_enabled`,
`peer_alive`, and router statistics. Runtime errors use
`MavlinkRuntimeError(source, error)`. Runtime/vehicle lifecycle callbacks receive
`MavlinkAction(source, vehicle=None, component=None, error=None)`.

## Async runtime

```text
AsyncMavlinkRuntime(
    endpoint=None,
    *,
    delivery_capacity=1024,
    action_capacity=1024,
    callback_concurrency=1,
    **runtime_options,
)
```

The logical API matches `MavlinkRuntime`. Lifecycle, transport send/request and
wait operations are awaited. Registration, `latest`, `add_filter`, `add_history`
and `prune_vehicles` are immediate operations. Async callbacks must be coroutine
functions.

`callback_concurrency=1` preserves callback order. A larger value enables
bounded concurrency for independent telemetry callbacks; lifecycle actions
remain ordered. Telemetry overflow drops the oldest callback and increments
`dropped_callbacks`; action overflow is a fatal delivery error.

## Vehicles and components

`runtime.vehicles` is a `MavlinkCollection`. An autopilot heartbeat establishes
a `MavlinkVehicle`; other source components are then attached to it.

Collection API:

- `get(system_id)`;
- `get_component(component_id)` across all vehicles;
- iteration and `len()`;
- `wait_for(timeout=None)`;
- `remove(identifier)` for disconnected state;
- `subscribe(message_type, callback=None, once=False, **options)`;
- `on_added`, `on_removed`, `on_connected`, `on_disconnected`, `on_error`, `on`.

Vehicle-specific API adds `get_component`, `get_components`,
`wait_for_component`, `remove_component`, component event helpers, targeted
transport and application operations. Component API provides the same targeted
operations without nested component management.

```python
vehicle = link.vehicles.get(12)
component = vehicle.get_component(1) if vehicle else None

if component:
    component.subscribe("HEARTBEAT", on_heartbeat)
    component.send_named("command_long", command=...)
```

`MavlinkVehicleState(connected, last_seen_monotonic,
last_observed_monotonic)` is returned by endpoint state. Heartbeats drive
connection state; every accepted message updates observed time for retention.
Async vehicle/component variants have the same names and properties but await
transport calls and waits.

Vehicle convenience hooks are `on_component_added`, `on_component_removed`,
`on_component_connected` and `on_component_disconnected`.

`vehicle_state_retention` automatically removes disconnected state after the
specified seconds. `prune_vehicles(older_than=...)` triggers explicit cleanup.
Removing connected state is rejected.

## Cache

```text
MessageCache(key, *, per_key_limit=64, max_keys=None)
```

Methods are `add`, `latest`, `all`, `snapshot`, and `clear(key=None)`; `keys`,
`len(cache)` and `stats` provide inspection. `MessageCacheStats` contains
`keys`, `messages`, and `evicted_keys`.

## History

```text
MessageHistory(
    *, limit=1000, background=False, queue_capacity=1024,
    batch_size=64, flush_interval=0.02,
)
```

`limit=None` is unbounded. `background=True` moves serialization to a bounded
writer. Methods: `append`, `query`, `latest`, `flush`, `clear`, `close`.
Queries accept `system_id`, `component_id`, `message_type`, inclusive `since`
and `until` Unix timestamps, plus tail `limit`.

```python
history = SqliteMessageHistory(
    "telemetry.sqlite3",
    limit=100_000,
    queue_capacity=4096,
    batch_size=128,
    flush_interval=0.02,
    wal=True,
    busy_timeout=5.0,
)
```

`SqliteMessageHistory` has the same query API. WAL is opt-in. Non-finite MAVLink
float values are stored as JSON `null`; live messages are unchanged.

`MessageRecord` fields: sequence, system/component IDs, message type,
`received_at`, and JSON payload. `HistoryWriterStats` reports `submitted`,
`processed`, `persisted`, `failed_records`, `queued`, `batches`, and `failed`;
access it through `writer_stats`.
`recording_error` exposes the original writer failure.

The runtime reports a permanent history failure once and detaches that history
from live traffic. Storage remains caller-owned and may still be inspected or
closed. A background history becomes closed after its writer has stopped even
when `close()` re-raises the stored recording error.

## Raw async channel

`MavlinkAsyncChannel(router, message_filter=None, maxsize=128, loop=None)` bridges
router callbacks to an asyncio queue. Use `start`, await `receive(timeout=None)`,
use `receive_nowait`, inspect `pending_messages`, then `stop`/`close`. Restart creates a fresh queue; stale
messages from a previous session are not delivered.

The `MavlinkMessage` protocol describes `get_header`, `get_type`, `get_msgId`,
`get_srcSystem`, `get_srcComponent`, `get_seq`, `get_msgbuf`, `to_dict` and
`to_json`. A compatible `MavlinkHeader` supplies source/sequence metadata.
