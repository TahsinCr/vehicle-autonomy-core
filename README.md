[![Python 3.11+][python-shield]][python-url]
[![Repository license][license-shield]][license-url]

**English** | [Türkçe][readme-tr-url]

# Vehicle Autonomy Core

Vehicle Autonomy Core is the shared Python core used by Kırlangıç Team's
vehicle projects. It brings together the infrastructure that an aircraft,
ground vehicle or another autonomous platform commonly needs: dependency
injection, in-process events, mission orchestration and MAVLink communication.

This repository is a toolkit, not a finished autonomy application. It does not
decide where a vehicle should move, which target should be selected or how a
payload should behave. Those decisions stay in the application built on top of
the core.

## Scope

The core provides:

- small `Model` and `Service` base contracts;
- synchronous and asyncio-native event buses;
- named event channels with a shared lifecycle;
- dependency registration, injection, scopes and deterministic cleanup;
- a vehicle-neutral mission engine with queues, priorities, retries and chains;
- a single-reader MAVLink connection and router;
- an asyncio bridge, application packets, peer liveness and request/response;
- bounded application dispatch workers and transport-safe remote-log models.

The core deliberately does not provide:

- guidance, navigation, control or path-planning algorithms;
- ARM, takeoff, landing or other vehicle-specific commands;
- mission selection rules for a particular product or competition;
- camera, computer-vision, target-tracking or payload implementations;
- a UI, ground-control station, database or logging backend;
- authentication, encryption or guaranteed delivery for application packets.

A useful boundary is: code that knows the vehicle's concrete task belongs in
the vehicle application; reusable coordination and transport mechanisms belong
here.

## Architecture

```text
vehicle application
├── domain services and vehicle integrations
├── concrete Mission classes
└── UI / configuration / persistence
             │
             ▼
Vehicle Autonomy Core
├── abstracts       common model and service contracts
├── dependency      object construction and ownership
├── events          in-process communication
├── mission         generic mission scheduling
└── mavlink         transport and application messaging
             │
             ▼
Python standard library + optional pymavlink
```

Dependencies point toward the core. The core never imports a vehicle project,
a UI framework or application-specific mission code.

## Requirements and installation

- Python 3.11 or newer
- `pymavlink` only when opening a real MAVLink connection
- no third-party runtime dependency for abstracts, events, dependency injection
  or missions

For local development without MAVLink:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Install the optional MAVLink dependency when it is needed:

```bash
python -m pip install -e '.[mavlink]'
```

On Windows, activate the environment with
`.\.venv\Scripts\Activate.ps1`.

### Using the repository as `src/core`

The intended integration is to place this repository at `src/core` in the
consuming project. A Git submodule is suitable for this layout:

```bash
git submodule add https://github.com/TahsinCr/vehicle-autonomy-core.git src/core
```

```text
your-project/
├── src/
│   ├── __init__.py
│   ├── core/                 # this repository
│   │   ├── __init__.py
│   │   ├── dependency/
│   │   ├── events/
│   │   ├── mission/
│   │   └── mavlink/
│   └── your_application/
└── tests/
```

Consumer imports remain straightforward:

```python
from src.core import DependencyContainer, EventBus, MissionEngine
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime
```

All package-internal imports are relative. The same checkout can therefore be
loaded below another parent package, such as `vehicle_stack.core`, without
changing the source.

## Module map

| Module | Purpose |
|---|---|
| `abstracts.py` | `Model` serialization and the `Service` lifecycle contract |
| `dependency/container.py` | containers, registration helpers, scopes, resolution and shutdown |
| `dependency/registration.py` | tokens, `Inject`, `Lifetime` and provider records |
| `dependency/injection.py` | constructor and function injection |
| `dependency/annotations.py` | type-hint and injection-marker parsing |
| `dependency/resolution.py` | resolution context and circular-dependency detection |
| `dependency/lifecycle.py` | cached-resource tracking and sync/async disposal |
| `dependency/errors.py` | dependency-specific exceptions |
| `events/event_bus.py` | thread-safe synchronous delivery |
| `events/async_event_bus.py` | asyncio-native delivery |
| `events/engine.py` | named sync and async event channels |
| `events/actions.py` | before, after, error and timeout hooks |
| `events/filtering.py` | event type and predicate filters |
| `events/history.py` | bounded in-memory history |
| `events/subscription.py` | cancellable subscription handles |
| `events/contracts.py` | delivery modes, error policies, results and statistics |
| `events/errors.py` | event bus exceptions |
| `mission/base.py` | base class for application-defined missions |
| `mission/controller.py` | abstract control boundary exposed to a mission |
| `mission/engine.py` | registry, shared state and the public mission facade |
| `mission/lifecycle.py` | ready-to-use pause, resume, stop, progress and completion component |
| `mission/scheduler.py` | ready-to-use queue, conflict, priority, retry and chain component |
| `mission/runtime.py` | engine-owned state and bound mission controller |
| `mission/models.py` | snapshots, events, retry policy and chain models |
| `mission/enums.py` | phases, priorities, policies and transition rules |
| `mission/errors.py` | mission-specific exceptions |
| `mavlink/endpoint.py` | validated serial, UDP and TCP endpoint settings |
| `mavlink/connection.py` | `pymavlink` transport ownership and serialized I/O |
| `mavlink/router.py` | the single receive loop, routes, waits, history and statistics |
| `mavlink/filter.py` | MAVLink metadata and predicate filters |
| `mavlink/message.py` | received-message envelopes |
| `mavlink/cache.py` | bounded thread-safe per-key message history |
| `mavlink/channel.py` | bounded router-to-asyncio bridge |
| `mavlink/application.py` | JSON packets and `V2_EXTENSION` fragmentation |
| `mavlink/peer.py` | peer state, liveness and correlated requests |
| `mavlink/dispatch.py` | bounded application handler execution |
| `mavlink/remote_log.py` | validated remote-log records and batches |
| `mavlink/runtime.py` | high-level lifecycle and messaging facade |
| `mavlink/protocols.py` | structural types for compatible MAVLink messages |

Files such as `dependency/annotations.py`, `dependency/resolution.py`,
`dependency/lifecycle.py` and `mission/runtime.py` are implementation modules.
Most applications should use the public exports from `src.core`,
`src.core.dependency`, `src.core.events`, `src.core.mission` and
`src.core.mavlink` instead of importing those files directly.

## Core contracts

### Model

`Model.to_dict()` returns the public state of a model. Dataclass fields and
normal instance or slot attributes whose names do not start with `_` are
included automatically.

```python
from dataclasses import dataclass

from src.core import Model


@dataclass(slots=True)
class Position(Model):
    latitude: float
    longitude: float
    _source: str = "gps"


position = Position(39.925, 32.836)
assert position.to_dict() == {
    "latitude": 39.925,
    "longitude": 32.836,
}
```

`to_dict()` exposes values; it is not a generic JSON encoder. Wire models that
need validation or defensive copies provide their own serialization methods.

### Service

`Service` is the shared lifecycle shape. A concrete service implements
`start()` and `stop()` and owns the resources it opens.

```python
from src.core import Service


class Worker(Service):
    def start(self) -> None:
        print("worker started")

    def stop(self) -> None:
        print("worker stopped")
```

## Dependency injection

`DependencyContainer` can use classes, factories or existing instances as
providers. Tokens may be classes or any other hashable value.

### Lifetimes

| Lifetime | Behavior |
|---|---|
| `transient` | creates a new value for every resolution |
| `singleton` | creates one value owned by the registering container |
| `scoped` | creates one value per child scope |

```python
from abc import ABC, abstractmethod

from src.core import DependencyContainer


class Clock(ABC):
    @abstractmethod
    def now(self) -> float: ...


class SystemClock(Clock):
    def now(self) -> float:
        import time
        return time.time()


class TelemetryService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock


container = DependencyContainer()
container.singleton(Clock, SystemClock)
container.transient(TelemetryService)

telemetry = container.resolve(TelemetryService)
container.shutdown()
```

Constructor annotations are used for autowiring. Use an explicit dependency
map when a parameter name or annotation is not enough:

```python
container.singleton("vehicle-id", instance="IKA-01")
vehicle = container.build(
    lambda identifier: {"vehicle": identifier},
    dependencies={"identifier": "vehicle-id"},
)
```

### Injection decorators

Missing parameters can be injected into a function or class. Caller-supplied
arguments are never overwritten.

```python
from typing import Annotated

from src.core import Inject


@container.inject
def timestamp(clock: Annotated[Clock, Inject()]) -> float:
    return clock.now()
```

`strict=True` requires an explicit registration for every annotated injection
candidate. An optional dependency can be declared with
`Inject(optional=True)`.

### Scopes and async providers

```python
root = DependencyContainer()
root.scoped(dict, factory=dict)

with root.create_scope() as first_scope:
    first = first_scope.resolve(dict)
    assert first is first_scope.resolve(dict)

with root.create_scope() as second_scope:
    assert second_scope.resolve(dict) is not first
```

Async factories use the async lifecycle:

```python
async def open_client() -> object:
    return object()


container.singleton("client", factory=open_client)
client = await container.resolve_async("client")
await container.shutdown_async()
```

`warmup()` and `warmup_async()` eagerly create selected cached providers in
priority order. `unregister()` disposes synchronous cached values before
removing their token; use `unregister_async()` for values with `aclose()`.
Shutdown tries every cached resource in reverse creation order and raises all
cleanup failures together when more than one resource fails.

For a project-owned composition root, subclass `BaseDependencyContainer` and
put registrations in `configure()`.

## Events

### Synchronous bus

`EventBus` is thread-safe. Without an executor, handlers run on the thread that
calls `publish()`.

```python
from dataclasses import dataclass

from src.core import EventBus


@dataclass(frozen=True)
class PositionChanged:
    latitude: float
    longitude: float


positions = EventBus[PositionChanged](history=100)
subscription = positions.subscribe(
    lambda event: print(event.latitude, event.longitude),
)

result = positions.publish(PositionChanged(39.925, 32.836))
assert result.delivered == 1

subscription.cancel()
positions.close()
```

Subscriptions can be limited and filtered:

```python
positions.once(lambda event: print("first:", event))
positions.subscribe(
    lambda event: print("next three:", event),
    times=3,
    predicate=lambda event: event.latitude > 0,
    replay=1,
)
```

Use `EventFilter` when the same filter is shared by several operations. With
history enabled, `latest()` returns the newest match and `query()` returns
stored matches. `wait_for()` blocks until a match arrives and returns `None` on
timeout.

`publish_every(event, interval, times=...)` publishes the same event on a
daemon schedule and returns a cancellable `Subscription`.

### Hooks and error policy

```python
from src.core import ErrorPolicy, EventBus


events = EventBus[str](
    error_policy=ErrorPolicy.ISOLATE,
    on_before=lambda event: print("before", event),
    on_after=lambda event, result: print("after", result.delivered),
    on_error=lambda context: print("handler failed", context.error),
    on_timeout=lambda context: print("wait timed out", context.timeout),
)
```

`ISOLATE` records handler failures in `PublishResult`. `RAISE` reports them as
an `ExceptionGroup`. Reusable hook sets can be collected in `EventBusActions`.
`stats` reports total published, delivered and failed calls.

An optional `Executor` lets a synchronous bus run callbacks on executor
threads. `publish()` still waits for those callbacks, so `PublishResult`
contains both submission and handler failures.

### Async bus

`AsyncEventBus` accepts async handlers and belongs to one running event loop.
Delivery is sequential by default and can be made concurrent.

```python
import asyncio

from src.core import AsyncEventBus, DeliveryMode


async def main() -> None:
    events = AsyncEventBus[str](
        history=20,
        delivery_mode=DeliveryMode.CONCURRENT,
    )

    async def receive(value: str) -> None:
        print(value)

    subscription = await events.subscribe(receive)
    await events.publish("vehicle.ready")
    await subscription.cancel()
    await events.close()


asyncio.run(main())
```

The async bus provides the same filtering, replay, `once`, `times`, history,
wait and periodic-publish tools. Its hooks must also be async.
`publish_threadsafe()` is available after the bus has been bound to its owning
running loop and returns a `concurrent.futures.Future`.

### Named channels

Use `EventEngine` when an application has several channels that share defaults
and should stop together:

```python
from src.core import EventEngine


with EventEngine(history=50) as events:
    events.subscribe("vehicle.position", print)
    events.once("vehicle.ready", lambda value: print("ready:", value))

    events.publish("vehicle.position", {"lat": 39.925, "lon": 32.836})
    ready = events.wait_for("vehicle.ready", timeout=0.1)
```

Channels are normalized to lowercase and created lazily. `channel()` returns a
specific bus, `add()` installs a custom bus, and `remove()` closes one channel.
`stop()` closes every owned channel and periodic publisher. `AsyncEventEngine`
offers the same model with awaitable operations and `AsyncEventBus` channels.

## Missions

The mission package separates vehicle behavior from orchestration. Applications
implement `Mission`; `MissionEngine` owns registration, threads and observable
state. Lifecycle and scheduling behavior is provided by two ready-to-use
components rather than hidden mixin inheritance.

### Defining a mission

```python
from src.core import Mission, MissionEngine, MissionPriority
from src.core.mission import MissionConflictPolicy, MissionRetryPolicy


class SurveyMission(Mission):
    priority = int(MissionPriority.NORMAL)
    resources = frozenset({"navigation", "camera"})
    tags = frozenset({"survey"})
    conflict_policy = MissionConflictPolicy.QUEUE
    tick_interval = 0.05
    timeout_seconds = 30.0
    retry = MissionRetryPolicy(attempts=2, delay=0.5)

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name)
        self._steps = 0

    def start(self) -> None:
        self.checkpoint("started")

    def tick(self, elapsed_seconds: float) -> None:
        self._steps += 1
        self.update_progress(min(self._steps / 10, 1.0))
        if self._steps == 10:
            self.complete({"samples": self._steps})

    def stop(self) -> None:
        # Close mission-owned hardware or subscriptions here.
        pass


mission = SurveyMission()
named_mission = SurveyMission(name="Survey area B")

with MissionEngine() as engine:
    engine.launch(mission)
    snapshot = engine.wait(mission, timeout=5.0)
    assert snapshot is not None
```

Every instance receives a positive unique integer ID. The default name is made
from the class name (`SurveyMission` becomes `Survey Mission`), and callers may
override it per instance.

Mission configuration is declared on the class:

| Attribute | Meaning |
|---|---|
| `priority` | smaller numbers have greater authority |
| `resources` | names of exclusively used resources |
| `blocks` | mission classes that cannot run alongside this mission |
| `tags` | labels used for group operations |
| `prerequisites` | mission classes that must previously succeed |
| `conflict_policy` | reject, queue or preempt lower-priority conflicts |
| `prerequisite_policy` | reject or queue while prerequisites are missing |
| `tick_interval` | delay between `tick()` calls |
| `timeout_seconds` | maximum execution duration, or `None` |
| `queue_timeout_seconds` | maximum queue duration, or `None` |
| `retry` | attempt count and delay for retryable failures |

`start()` prepares work, `tick()` advances it, and `stop()` releases resources.
`pause()` and `resume()` may be overridden when the concrete mission supports
them. From inside a mission, use `checkpoint()`, `update_progress()`,
`complete()`, `fail()` and `wait_for_stop()` to communicate with the engine.

### Scheduling and control

`launch_many()` and its alias `run_parallel()` start all non-conflicting
missions. Conflicts are detected from shared resources and `blocks`. A mission
with `QUEUE` waits; `PREEMPT_LOWER` can stop conflicting work only when it has
strictly greater priority.

Engine commands accept either a `Mission` object or its integer ID:

```python
engine.pause(mission)
engine.resume(mission.id)
engine.stop_mission(mission, reason="operator request")
engine.cancel(mission.id)
```

A running mission may act through its bound `control`, but it cannot control a
higher-priority mission. `stop_missions(tags=..., resources=...)` selects
authorized active work without requiring direct references to those missions.

`snapshot()`, `snapshots()` and `manager_snapshot()` provide frozen runtime
records detached from caller-owned mappings. `events` and `transitions` are
normal `EventBus` instances. Historical events can be filtered with
`MissionEventQuery`:

```python
from src.core.mission import MissionEventLevel, MissionEventQuery


important = engine.query_events(
    MissionEventQuery(minimum_level=MissionEventLevel.WARNING, limit=50)
)
```

### Lifecycle and scheduler components

`MissionEngine()` creates `MissionLifecycle` and `MissionScheduler`
automatically, so normal usage does not require any extra setup. The same
classes are public when an application wants to use them directly or extend one
focused part of the engine:

```python
from src.core import MissionEngine, MissionLifecycle, MissionScheduler


class ObservedLifecycle(MissionLifecycle):
    def progress(self, mission, value, *, reason=""):
        print(f"mission progress: {value:.0%}")
        return super().progress(mission, value, reason=reason)


lifecycle = ObservedLifecycle()
scheduler = MissionScheduler()
engine = MissionEngine(lifecycle=lifecycle, scheduler=scheduler)

assert engine.lifecycle is lifecycle
assert engine.scheduler is scheduler
```

The engine binds each component to one owner. Existing calls such as
`engine.launch()`, `engine.pause()` and `engine.wait()` remain the main facade
and delegate to these components. The same operations are also available
through `engine.scheduler` and `engine.lifecycle` when direct component access
is useful. A custom component subclasses only the behavior it needs; the engine
itself no longer uses multiple inheritance.

### Mission chains

A chain creates and runs mission classes in order:

```python
from src.core import MissionChain


chain = MissionChain(
    "survey-sequence",
    (SurveyMission, SurveyMission),
    stop_on_failure=True,
)
engine.start_chain(chain)
state = engine.chain_snapshot("survey-sequence")
```

Chain entries are classes rather than instances. By default they must support a
no-argument constructor. Supply `mission_factory=` to `MissionEngine` when the
application needs dependency-backed construction.

Mission workers and the scheduler use daemon threads. `stop()` is cooperative:
a mission that blocks indefinitely in `start()` or `tick()` cannot be made safe
by the engine. If a worker does not finish within `stop_timeout`, the engine
raises `MissionTimeoutError` and keeps the stopping state visible so shutdown
can be retried.

## MAVLink

The MAVLink package can be used at two levels. `MavlinkRuntime` is the usual
entry point. The connection, router, async channel, application channel, peer
and dispatcher remain public when an application needs custom ownership.

### Endpoints and high-level runtime

```python
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime


endpoint = MavlinkEndpoint.udp(
    "0.0.0.0",
    14550,
    source_system=245,
    source_component=190,
    heartbeat_timeout=10.0,
)

with MavlinkRuntime(endpoint) as mavlink:
    subscription = mavlink.on(
        ("HEARTBEAT", "GLOBAL_POSITION_INT"),
        lambda message: print(message.to_dict()),
    )
    position = mavlink.wait_for("GLOBAL_POSITION_INT", timeout=3.0)
    latest_heartbeat = mavlink.latest("HEARTBEAT")
    subscription.cancel()
```

Use `MavlinkEndpoint.tcp(host, port)` for a TCP client and
`MavlinkEndpoint.serial(device, baud=...)` for a serial link. A plain
`host:port` URI is normalized to a TCP client URI. Network ports, source IDs,
baud and heartbeat timeout are validated before a connection is opened.

`MavlinkRuntime.start()` opens the client first and then its application
components. `stop()` closes them in reverse order and preserves every cleanup
error. `reconnect()` performs a complete stop/start cycle. `state` combines
transport, application-peer and router information; lifecycle errors are
published through `runtime.errors`.

### Filters, history and sending

```python
from src.core.mavlink import MavlinkMessageFilter


position_filter = MavlinkMessageFilter.for_types(
    "GLOBAL_POSITION_INT",
    source_systems={1},
    source_components={1},
    predicate=lambda message: message.relative_alt >= 0,
)

subscription = mavlink.on(position_filter, print)
mavlink.send_named(
    "command_long_send",
    target_system=1,
    target_component=1,
    command=511,
    confirmation=0,
    param1=33,
    param2=2,
    param3=0,
    param4=0,
    param5=0,
    param6=0,
    param7=0,
)
```

Filters may combine message type, message ID, source system, source component,
a native `pymavlink` condition and a Python predicate. `once()` removes itself
after the first match. Router `history()` returns `MavlinkMessageEnvelope`
objects; `latest()` returns the underlying message. `MavlinkClient` also
exposes `request_message_rate()`, `send()`, `call_mav()` and `call_raw()`.

`send_named()` and `call_mav()` invoke methods on `connection.mav`; they are
low-level MAVLink calls, so their parameters must match the selected dialect.

### Single-reader rule

```text
serial / UDP / TCP
        │
        ▼
MavlinkConnection       transport and serialized writes
        │
        ▼
MavlinkMessageRouter    the only recv_match() loop
        │
        ├── filtered subscribers
        ├── cache, history and waiters
        ├── MavlinkAsyncChannel
        └── MavlinkApplicationChannel
```

After the router starts, no other component should call `recv_match()` on the
same connection. Competing readers lose messages nondeterministically.

Router callbacks run on the receive thread. Keep them short. Use an
application queue, `MavlinkAsyncChannel` or `MavlinkApplicationDispatcher` for
slow work. A router stop raises `TimeoutError` if the receive thread remains
alive and leaves the connection open instead of closing it under that thread.

### Asyncio bridge

```python
from src.core.mavlink import MavlinkAsyncChannel


async def consume(router) -> None:
    channel = MavlinkAsyncChannel(router, "ATTITUDE", maxsize=32)
    channel.start()
    try:
        message = await channel.receive(timeout=1.0)
        print(message)
    finally:
        channel.stop()
```

The channel must be started from its owning event loop unless a loop was
supplied explicitly. When full, it discards the oldest item and increments
`dropped_messages`. `stop()` cancels forwarding and clears the queue, so a
restart never delivers stale messages from the previous session.

### Application packets

Give `MavlinkRuntime` an `application_role` to enable application messaging on
the same physical link:

```python
from src.core.mavlink import MavlinkApplicationResult, MavlinkRuntime


def read_health(packet):
    return MavlinkApplicationResult.success(
        {"healthy": True},
        message="health available",
    )


with MavlinkRuntime(endpoint, application_role="vehicle") as mavlink:
    handler = mavlink.handle("vehicle.health.get", read_health)
    mavlink.notify("mission.status", {"running": True})

    response = mavlink.request(
        "camera.capture",
        {"mode": "single"},
        timeout=3.0,
    )
    handler.cancel()
```

The sender serializes a JSON object, fragments it into MAVLink
`V2_EXTENSION` payloads and adds CRC32 integrity checking. The assembler accepts
out-of-order fragments, isolates sources by system/component and packet ID,
rejects conflicting duplicates, and expires incomplete assemblies.

`MavlinkApplicationPacket` validates packet type, ID, timestamp, source IDs and
JSON compatibility. `to_dict()` returns a detached dictionary. For protocol
tests or offline processing, use `MavlinkApplicationCodec.encode()` and feed
the resulting fragments to `MavlinkApplicationAssembler.accept()`.

`MavlinkApplicationPeer` adds heartbeats, ping/pong liveness and response
correlation. `MavlinkApplicationDispatcher` subscribes to peer packets and runs
registered handlers in a bounded thread pool. A handler may return
`MavlinkApplicationResult`, a mapping or `None`. Requests receive an automatic
`system.ack` or `system.error`; notifications do not require a response.

Packet types used for liveness and acknowledgements under `system.*` are
reserved. Application types should be namespaced, for example
`camera.capture`, `mission.status` or `logs.push`.

This protocol detects malformed or corrupted packets. It does not encrypt,
authenticate or guarantee delivery. Apply the security, authorization and
retry policy required by the consuming system.

### Remote logs

Remote-log classes are wire models; they do not collect or persist logs.

```python
from src.core.mavlink import (
    MavlinkRemoteLogBatch,
    MavlinkRemoteLogLevel,
    MavlinkRemoteLogRecord,
)


record = MavlinkRemoteLogRecord(
    sequence=1,
    source="mission",
    action="started",
    message="Survey started",
    level=MavlinkRemoteLogLevel.INFO,
    details={"mission_id": 42},
)
batch = MavlinkRemoteLogBatch("vehicle-2026-08-06", (record,))
payload = batch.to_payload()
```

Records validate text, timestamps and JSON-compatible details. Batches require
strictly increasing sequence numbers and enforce record, detail and encoded
size limits. UI-specific severity names are intentionally not part of the core.

### Message cache and structural types

`MessageCache` is useful outside the router when a bounded history per key is
needed:

```python
from src.core.mavlink import MessageCache


cache = MessageCache(lambda item: item["type"], per_key_limit=10)
cache.add({"type": "position", "value": 1})
latest = cache.latest("position")
```

`MavlinkMessageEnvelope` captures the router sequence, receive time, message
type, ID and source metadata around a raw message. `MavlinkHeader` and
`MavlinkMessage` are runtime-checkable structural contracts for tests and
adapters; users do not need to subclass them.

## Lifecycle and concurrency notes

- Event handlers are called outside bus locks.
- `EventBus` is thread-safe; `AsyncEventBus` is confined to one event loop.
- MAVLink router subscribers execute on the receive thread.
- Dispatcher handlers execute in worker threads with a bounded pending count.
- Dispatcher stop rejects new work, cancels work that has not begun, waits for
  running handlers and prevents late responses after shutdown.
- Mission implementations execute in their own worker threads and must
  cooperate with stop requests.
- Router, peer, mission and runtime shutdown failures remain observable; a
  timeout is not silently treated as successful shutdown.
- Long-running queues and histories are bounded where their owner exposes a
  capacity.
- A successful heartbeat proves link activity, not vehicle readiness or sensor
  health.

## Testing

Run the complete hardware-free suite from the repository root:

```bash
python tests/run.py
```

The script discovers every `test*.py` file below `tests` and returns a non-zero
exit code when a test fails. The equivalent direct command and the source
compilation check are:

```bash
python -m unittest discover -v
python -m compileall -q .
```

Run one package while developing:

```bash
python -m unittest discover -s tests/dependency -t . -v
python -m unittest discover -s tests/events -t . -v
python -m unittest discover -s tests/mission -t . -v
python -m unittest discover -s tests/mavlink -t . -v
```

The package-layout tests create temporary, real package trees for both
`src.core` and another parent package. They verify the intended submodule
layout through normal imports in clean subprocesses instead of an embedded
custom loader. MAVLink tests use fakes and do not require a flight controller.
Serial, radio, network and hardware-in-the-loop behavior must still be tested
by the consuming vehicle project.

## Contributing

Before adding a feature, check that unrelated vehicle projects could use it
without importing product concepts. Keep public imports stable where practical,
add tests for lifecycle and failure paths, and preserve these rules:

- one reader for each physical MAVLink connection;
- no UI or vehicle-task dependencies in the core;
- explicit ownership and cleanup of threads, loops and I/O;
- bounded queues and histories on continuous paths;
- no autonomous decision hidden inside transport code.

Release notes are kept in [CHANGELOG.md][changelog-url].

## License

Copyright © 2026 TahsinCr.

Vehicle Autonomy Core is licensed under GNU General Public License v3.0 only
(`GPL-3.0-only`). See [LICENSE][license-url] for the complete license and
[COPYRIGHT][copyright-url] for the copyright notice.

<!-- Badges -->

[python-shield]: https://img.shields.io/badge/Python-3.11%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white
[license-shield]: https://img.shields.io/github/license/TahsinCr/vehicle-autonomy-core.svg?style=for-the-badge

<!-- Links -->

[python-url]: https://www.python.org/downloads/
[readme-tr-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/README-TR.md
[changelog-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/CHANGELOG.md
[license-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/LICENSE
[copyright-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/COPYRIGHT
