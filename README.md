[![Python 3.10+][python-shield]][python-url]
[![Repository license][license-shield]][license-url]

**English** | [Türkçe][readme-tr-url]

# Vehicle Autonomy Core

Vehicle Autonomy Core is a reusable Python core for autonomous vehicle
projects. It brings together the infrastructure that an aircraft, ground
vehicle or another autonomous platform commonly needs: dependency injection,
in-process events, mission orchestration and MAVLink communication.

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

- Python 3.10 or newer
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
| `mission/scheduler.py` | ready-to-use queue, conflict, priority and retry component |
| `mission/orchestration.py` | internal coordination between execution components |
| `mission/chain.py` | sequential chains, context handoff and mixed-stage advancement |
| `mission/parallel.py` | controlled parallel groups and aggregate results |
| `mission/background.py` | owner-bound background mission policies |
| `mission/execution.py` | immutable chain, node, group and ownership models |
| `mission/runtime.py` | engine-owned state and bound mission controller |
| `mission/models.py` | lifecycle snapshots, events, queries and retry policy |
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
| `mavlink/async_runtime.py` | async lifecycle using the shared transport |
| `mavlink/vehicles.py` | discovered vehicles, components and source-scoped routing |
| `mavlink/actions.py` | decorator actions and bounded async callback delivery |
| `mavlink/handlers.py` | source-scoped application handlers and async task ownership |
| `mavlink/protocols.py` | structural types for compatible MAVLink messages |

Files such as `dependency/annotations.py`, `dependency/resolution.py`,
`dependency/lifecycle.py`, `mission/orchestration.py`, `mission/chain.py`,
`mission/parallel.py`, `mission/background.py` and `mission/runtime.py` are
implementation modules.
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
cleanup failures together when more than one resource fails. Concurrent
resolutions still receive one scoped instance, and an object registered under
several tokens remains open until its final owning token is removed. A
synchronous shutdown that encounters async-only cleanup leaves ownership intact
so the application can retry with `shutdown_async()`.

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
timeout. Replay is a strict subscription boundary: matching live events that
arrive during replay are delivered afterwards, so they cannot overtake history.
For hot paths, pass `limit=` to `query()` so the backward scan stops as soon as
enough recent matches have been found.
Filtered reads first snapshot the retained history, then evaluate predicates
outside its lock. Concurrent writes or changes made by a predicate do not
alter that snapshot. The copy costs memory proportional to history size even
with `limit=`; unfiltered limited reads copy only the requested tail.

`publish_every(event, interval, times=...)` publishes the same event on a
daemon schedule and returns a cancellable `Subscription`. A bus accepts at
most 64 live periodic schedules by default; set `max_schedules=` when the
application has a different, deliberate limit. `replay_buffer_limit=` bounds
live events arriving behind a slow replay. Overflow raises `BufferError`
instead of silently producing an incomplete event sequence.

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
| `timeout_seconds` | maximum active execution duration, excluding pauses, or `None` |
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

`MissionEngine(max_active_missions=..., max_queued_missions=...)` adds global
backpressure when the application needs it. Both limits are optional. Once the
active limit is reached, otherwise launchable work waits in priority order;
the engine rejects another queued mission after the queue limit is reached.

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

### Mission orchestration

A chain creates mission classes in order. Each run has its own immutable
context, so a mission can read the initial input and the previous result without
receiving orchestration data through its constructor:

```python
from src.core import Mission, MissionChain


class ReadTarget(Mission):
    def start(self):
        target = self.runtime.chain_context.input["target"]
        self.complete({"target": target, "ready": True})

    def stop(self):
        pass


class UseTarget(Mission):
    def start(self):
        previous = self.runtime.chain_context.previous_result
        self.complete({"accepted": previous["ready"]})

    def stop(self):
        pass


chain = MissionChain("target-flow", (ReadTarget, UseTarget))
run = engine.start_chain(chain, input={"target": "zone-a"})
state = engine.chain_snapshot(run.execution_id)
```

`context.results` keeps completed results under node names. Repeated mission
types receive stable suffixes, or an explicit `MissionNode` can provide the
name. `stop_on_failure=True` remains the default. With `False`, the next stage
also receives `previous_mission.phase`, allowing it to handle a terminal result
deliberately.

A controlled parallel group adds aggregate status and a failure policy to the
existing independent `run_parallel()` helper:

```python
from src.core import (
    MissionNode,
    MissionParallelGroup,
    ParallelFailurePolicy,
)


group = MissionParallelGroup(
    "checks",
    (
        MissionNode("health", HealthCheck),
        MissionNode("position", PositionCheck),
    ),
    ParallelFailurePolicy.CANCEL_REMAINING,
)
run = engine.start_parallel(group)
state = engine.wait_parallel(run.execution_id, timeout=5.0)
engine.cancel_parallel(run.execution_id)  # propagated to active children
```

`WAIT_ALL` lets every child reach a terminal state. `CANCEL_REMAINING` cancels
active siblings after a failure, while `STOP_REMAINING` stops them. Shared
resources and `blocks` are checked before the group starts. Completed values
are available as the immutable `state.result` mapping.

A parallel group can also be one chain stage. Both children receive the result
from `Prepare`; `Finish` receives the combined `left` and `right` results:

```python
from src.core import MissionParallelStage


parallel = MissionParallelStage(
    "work",
    (MissionNode("left", LeftWork), MissionNode("right", RightWork)),
    ParallelFailurePolicy.STOP_REMAINING,
)
chain = MissionChain("mixed-flow", (Prepare, parallel, Finish))
engine.start_chain(chain)
```

Long-lived supporting work remains a normal mission and can be attached to a
mission, chain run or parallel run:

```python
from src.core import BackgroundFailurePolicy, OwnerTerminationPolicy


foreground = ForegroundMission()
engine.launch(foreground)
engine.launch_background(
    StatusPublisher(),
    owner=foreground,
    termination_policy=OwnerTerminationPolicy.STOP_WITH_OWNER,
    failure_policy=BackgroundFailurePolicy.FAIL_OWNER,
)
```

The safe default stops the background mission when its owner ends.
`CANCEL_WITH_OWNER` preserves cancellation semantics, and `KEEP_RUNNING` must
be selected explicitly. `stop_chain()`, `cancel_chain()`, `stop_parallel()` and
`cancel_parallel()` propagate through normal mission lifecycle calls; no extra
worker-thread mechanism is introduced.

`wait_chain()` and `wait_parallel()` provide blocking terminal waits without
polling. Completed chain and parallel snapshots are retained up to
`execution_history` (256 by default). `forget_chain()` and
`forget_parallel()` remove a retained result earlier when the application no
longer needs it. Mission instances created for a forgotten orchestration run
are also released from the engine registry once they are terminal.

Chain and group entries are classes rather than instances. By default they must
support a no-argument constructor. Supply `mission_factory=` to
`MissionEngine` when the application needs dependency-backed construction.

Mission workers and the scheduler use daemon threads. `stop()` is cooperative:
a mission that blocks indefinitely in `start()` or `tick()` cannot be made safe
by the engine. If a worker does not finish within `stop_timeout`, the engine
raises `MissionTimeoutError` and keeps the stopping state visible so shutdown
can be retried. The engine never calls `start()`, `tick()`, `pause()`, `resume()`
or `stop()` concurrently on the same mission instance. Transition subscribers
run outside the engine state lock and may issue another lifecycle command.
Calling `complete()` or `fail()` inside `start()`/`tick()` ends that callback
immediately; terminal state and resource release occur only after it unwinds.
Parallel stage results identify their group through `node` and carry
`mission_id=None` instead of a completion-order-dependent child ID.

## MAVLink

The MAVLink package can be used at two levels. `MavlinkRuntime` is the usual
entry point. The connection, router, async channel, application channel, peer
and dispatcher remain public when an application needs custom ownership.

The router can reject unwanted traffic before it reaches latest state, cache,
history, vehicle discovery or subscribers. `add_filter()` accepts any number
of synchronous envelope predicates and returns a cancellable `Subscription`.
It works both directly and as a decorator:

```python
@link.add_filter
def known_systems(envelope):
    return envelope.source_system in {1, 2, 3}

message_types = link.add_filter(
    lambda envelope: envelope.message_type in {
        "HEARTBEAT",
        "ATTITUDE",
        "GLOBAL_POSITION_INT",
    }
)

# Stop applying only the message-type filter.
message_types.cancel()
```

Filters run in registration order and stop at the first rejection. They execute
on the receive thread, so keep them fast and non-blocking. An exception rejects
that message and is published as a router error with phase `filter`.

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
    subscription = mavlink.subscribe(
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

### Multiple vehicles and components

Use `MavlinkRuntime` for synchronous callbacks or `AsyncMavlinkRuntime` for
async callbacks. Both use a single receive thread per connection. Vehicle
discovery requires an autopilot heartbeat; GCS and companion-only systems do
not create vehicle entries. Components of an identified vehicle are discovered
from their messages. Systems sharing a link must have distinct system IDs.

```python
link = MavlinkRuntime(endpoint, heartbeat_timeout=5.0, vehicle_history=128)

@link.vehicles.on_added
def discovered(event):
    print("Discovered:", event.vehicle.system_id)

@link.vehicles.subscribe("GLOBAL_POSITION_INT")
def position(event):
    print(event.source_system, event.source_component, event.message.lat)

with link:
    vehicle = link.vehicles.wait_for(timeout=5.0)
    if vehicle is not None:
        vehicle.request_message_rate("GLOBAL_POSITION_INT", frequency_hz=10)
        component = vehicle.get_component(1)
        if component is not None:
            subscription = component.subscribe("HEARTBEAT", print)
            subscription.cancel()
```

Register discovery handlers before entering the context to observe initial
discovery. `vehicles.get(12)` only looks up an existing object and returns
`None` when absent. `wait_for(timeout=...)` waits for any connected endpoint,
returns `None` on timeout or runtime stop, and does not accept an ID.
Use `vehicle.get_component(id)` for one component (or `None`) and
`vehicle.get_components()` for a tuple snapshot of all its components.
`vehicle.wait_for_component(timeout=...)` waits for a connected component
(await it in async mode). `remove_component(id)` removes a disconnected one.
Discovery and connection hooks live directly on the vehicle:
`on_component_added`, `on_component_removed`, `on_component_connected` and
`on_component_disconnected`; callbacks and decorators are both supported.
Iteration is a snapshot, so a bulk operation is explicit:

```python
for vehicle in link.vehicles:
    vehicle.request_message_rate("ATTITUDE", frequency_hz=10)
```

Subscriptions on `link.vehicles`, one vehicle or one
component receive `MavlinkMessageEnvelope` with the corresponding source
scope. Collection subscriptions also cover future discoveries. Decorators
return a callable `CallbackSubscription`; direct registration returns the same
object whose
`cancel()` is synchronous in both modes. `once=True` consumes a subscription
on delivery. Scope `latest(type)` and `history(type=None)` return source-scoped
envelopes; `wait_for(type, timeout=...)` waits for a new message. History is
bounded by `vehicle_history` per vehicle and per component.

Named actions also accept decorators or callbacks:

```python
@vehicle.on_disconnected(once=True)
def disconnected(event):
    print(event.vehicle.system_id)

vehicle.on("error", lambda event: print(event.error))
```

Runtime actions are `on_start`, `on_stop`, `on_error`. Vehicles and components
have `on_connected`, `on_disconnected` and `on_error`. The fleet collection has
`on_added` and `on_removed`; component discovery/removal/connection callbacks
are registered through the vehicle's `on_component_*` methods. Action callbacks
receive `MavlinkAction` with `source`, `vehicle`, `component` and `error` as
applicable.

Heartbeat expiry marks an endpoint disconnected without removing it. A later
heartbeat reuses the object and its subscriptions. Vehicle liveness means at
least one component is still sending heartbeats; targeted vehicle commands
additionally require a live, discovered autopilot component. `remove(id)` is
allowed only for disconnected endpoints and cancels their subscriptions.
Sending through a component targets that component; sending through a vehicle
targets its discovered autopilot. `send_named()` is for messages accepting
target fields and rejects caller-supplied target overrides. `send(message)`
copies and targets messages without mutating the caller's object. `notify()` and
`request()` use the configured application peer with explicit source correlation.
The global peer state and router cache remain connection-level diagnostics.

```python
from src.core.mavlink import AsyncMavlinkRuntime

async def receive_positions(endpoint):
    link = AsyncMavlinkRuntime(endpoint, delivery_capacity=1024)

    @link.vehicles.subscribe("GLOBAL_POSITION_INT")
    async def position(event):
        print(event.source_system, event.message.lat)

    async with link:
        vehicle = await link.vehicles.wait_for(timeout=5.0)
        if vehicle is not None:
            await vehicle.request_message_rate("GLOBAL_POSITION_INT", 10)
            message = await vehicle.wait_for("GLOBAL_POSITION_INT", timeout=5.0)
            print(message)
```

There is no `.aio` view: discovered objects follow their runtime's mode.

Optional recording is separate from `latest()`, which now keeps the last
message per type even after history eviction (per source/type on the router).
Last-known data may be stale: check timestamps and connection state.

```python
from src.core.mavlink import MessageHistory, SqliteMessageHistory

with SqliteMessageHistory("telemetry.sqlite3", limit=None) as history:
    with MavlinkRuntime(endpoint) as link:
        recording = link.add_history(history)  # also works after startup
        # Run your application's receive/wait workflow here.
        rows = history.query(system_id=12, component_id=1,
                             message_type="ATTITUDE", limit=20)
        last = history.latest(system_id=12, message_type="ATTITUDE")
        recording.cancel()
```

Use `MessageHistory(limit=1000)` for memory storage. Both backends default to
1000 total records; `limit=None` is unlimited. SQLite retention includes earlier
runs. `query()` returns detached JSON `MessageRecord` snapshots oldest-first,
with source/type filters and inclusive Unix time bounds `since`/`until`.
The query limit selects the newest matching records. `clear()` removes all
records. Memory tail queries stop once enough matches are found; queries with
no matches can still scan the full history. SQLite applies filters and limits
in SQL. Source IDs must be integers from 0 to 255; time bounds must be finite
and ordered, and message types cannot be empty.
Messages must implement JSON-compatible `to_dict()`. MAVLink non-finite float
sentinels (`NaN`, positive infinity and negative infinity) are stored as JSON
`null`; the live message object is not modified.

`add_history` is synchronous in both runtime modes, records future traffic and
returns a cancellable subscription. Runtime close detaches it; the application
owns storage and closes it after runtime shutdown. Subclass `MessageHistory`
for another backend. Storage errors are reported with runtime error source
`history`. SQLite JSON encoding and batched commits run on a dedicated bounded
writer, not the receive thread. `queue_capacity=1024` limits pending messages;
`batch_size=64` and `flush_interval=0.02` tune transaction batching. Queue
overflow rejects the
new record and marks `recording_error`; disk failures are visible through that
property and raised by `flush()`, queries and `close()`. Check these errors even
when no more messages arrive. `flush(timeout=5.0)` waits for previously accepted
records; queries/clear flush before accessing SQLite and close drains the writer.
No bounded recorder guarantees lossless storage under unlimited load.
Unlimited storage
requires monitoring available memory/disk space. Existing `vehicle.history()`
remains a bounded diagnostic view, independent of these optional recorders.

To find the same component ID across all discovered vehicles, use
`link.vehicles.get_component(1)`. It returns a tuple snapshot of existing
component objects (including disconnected ones), or `()` when none match.
Use `component.system_id` to identify its vehicle, and `component.state.connected`
to filter live results. In both runtime modes this lookup is synchronous:

```python
for component in link.vehicles.get_component(1):
    if component.state.connected:
        print(component.system_id, component.component_id)
```

Async lookup/registration/cancellation remain local synchronous operations;
message waits, sending, application requests and lifecycle operations are
awaitable. Blocking transport operations use the loop's shared executor.
Cancellation waits for an already-started transport operation to finish, so
executor work is not left detached; it cannot retract a message already sent.
Async callback delivery uses one consumer with coalesced cross-thread wakeups.
Telemetry and lifecycle actions have separate bounded queues. When telemetry
is full, its oldest callback is dropped; `link.dropped_callbacks` exposes the
count. Actions run first, in order, so an `on_added` callback can register
`on_connected` or component discovery callbacks for the same discovery sequence.
`action_capacity` defaults to 1024. Exhausting it sets `link.delivery_error`,
makes `link.running` false and reports the fault through `on_error`; stop and
restart the runtime to recover. Increase the capacity for larger discovery bursts.
While faulted, runtime and scoped send/request/wait operations reject new calls
with `RuntimeError` chained from the delivery error. Pending scoped waits wake
when the loop processes the fault notification. Snapshot lookups and history
remain readable. Already-started blocking transport calls are not retracted;
raw waits observe the fault when their underlying wait returns. Direct access
to the low-level client/connection bypasses the runtime's fault guard.
Slow callbacks delay other callbacks,
but not socket reading; message/discovery waits wake independently of callbacks.
Pending callback deliveries are discarded on stop and are not replayed on restart.
Running handlers are cancelled; a handler ignoring cancellation causes an
explicit shutdown timeout. Runtime start/stop hooks are awaited directly.
Telemetry recipients are snapshotted on
receipt: a later subscription does not receive older queued messages. Cancelled
subscriptions are skipped at delivery. Lifecycle actions resolve handlers at
delivery so discovery hooks can install subsequent connection hooks.
Synchronous start/stop operations are serialized; close waits for startup to
finish before disposing resources. Calls from owned threads reject conflicting
lifecycle operations rather than deadlocking on a thread join.

High-level synchronous message/discovery callbacks, predicates and hooks run
on one shared callback worker, not the receive thread. `callback_capacity`
(default 1024) bounds pending telemetry deliveries; overflow drops the oldest
telemetry and counts it in `dropped_callbacks`. Lifecycle actions use a separate
FIFO with `callback_action_capacity=1024`; telemetry cannot evict them. Action
overflow or fatal worker exit sets `delivery_error` and makes `running` false;
stop/start is required to recover. Slow callbacks delay other callbacks, not queue
submission. Pending deliveries are discarded on stop. An active synchronous
callback cannot be killed; shutdown reports a timeout if it does not return.
Explicit start/stop/removal hooks run on the lifecycle caller. Low-level router
subscriptions, EventBus subscriptions and synchronous history writers still
run on their emitting thread; the worker guarantee applies to high-level
runtime/vehicle/component subscriptions, not these lower-level APIs.

Callback registrations support `once`, `max_calls`, `frequency_hz`, `timeout`,
`predicate` and `enabled`. `frequency_hz` is an execution-rate ceiling, not a
periodic scheduler: excess events are skipped. Disabled/filtered/rate-limited
events do not consume the call budget. `once` and `max_calls` cannot be combined.

```python
@vehicle.subscribe("ATTITUDE", frequency_hz=10, timeout=0.5, max_calls=100)
def attitude(event):
    print(event.message)

@attitude.on_error
def failed(context):
    print(context.error)

attitude.on_success(lambda context: print("processed"))
attitude.disable()
attitude.enable()
```

`on_before`, `on_success`, `on_error`, `on_timeout` and `on_after` can be passed
at registration or added as methods/decorators. They receive `CallbackContext`
with `event`, `result`, `error`, and elapsed seconds. Async registrations require
async callbacks/hooks. Sync timeouts are observed after return; async timeouts
request cancellation of the callback. Framework overruns raise
`CallbackTimeoutError`; a `TimeoutError` raised by user code follows the normal
error path. Hooks themselves have no separate time
budget. Blocking async code or code ignoring cancellation cannot be forcibly
interrupted. `on_after` runs in cleanup after an admitted invocation; skipped
events have no execution hooks. Calling the decorator result directly invokes
the original function, bypassing the event execution policy.
Ordinary hook failures do not skip later hooks in the same group. Success and
cleanup failures reach local error hooks; multiple callback/hook failures are
preserved in an exception group. Cancellation still propagates.

Discovered identity fields are read-only. A vehicle selects another connected
autopilot component if its current autopilot is removed or times out.
Concurrent `close()` calls wait for the same cleanup. Cancelling an async caller
does not cancel the shared close operation.

Application handlers can be registered with `@link.handle("command.name")`,
`@vehicle.handle("command.name")` or `@component.handle("command.name")`.
The most specific matching handler wins: component, vehicle, then runtime.
Registration returns a cancellable subscription when a callback is passed
directly; duplicate registrations require `replace=True`. They share the
bounded application dispatcher, not a worker pool per vehicle. Use ordinary
functions with `MavlinkRuntime` and `async def` with `AsyncMavlinkRuntime`;
async application handlers run on the runtime's loop and are cancelled and
awaited at shutdown.

Async runtime also provides awaitable `send`, `send_named`, `notify`, `request`
and raw-message `wait_for`. Its `messages`, `packets` and `errors` are
`AsyncEventBus` instances: use `await link.messages.subscribe(callback)`.
The high-level `link.subscribe(...)` and scoped subscription methods remain
synchronous registration operations and support decorators and `once=True`.

`with` and `async with` close the whole shared connection and owned services.
Do not open or close separate connections for discovered vehicle objects.
The connection still performs its initial heartbeat handshake before runtime
startup completes; its timeout is `MavlinkEndpoint.heartbeat_timeout`.

Migration: `runtime.on(message_type, callback)` is now
`runtime.subscribe(message_type, callback)`. `on()` denotes lifecycle actions.
For multiple vehicles, use scoped APIs instead of the connection's default
target or its shared message cache.

### Filters, history and sending

```python
from src.core.mavlink import MavlinkMessageFilter


position_filter = MavlinkMessageFilter.for_types(
    "GLOBAL_POSITION_INT",
    source_systems={1},
    source_components={1},
    predicate=lambda message: message.relative_alt >= 0,
)

subscription = mavlink.subscribe(position_filter, print)
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

Router callbacks run on the receive thread. They must not perform model
inference, disk I/O, network requests or other blocking work. Use an application
queue, `MavlinkAsyncChannel` or `MavlinkApplicationDispatcher` for those jobs.
A router stop raises `TimeoutError` if the receive thread remains
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
supplied explicitly. `maxsize` bounds one thread-safe pending queue. On
overflow, the oldest pending message is always dropped so telemetry stays
latest-biased; every drop increments `dropped_messages`. `stop()` cancels
forwarding, clears the queue and wakes blocked receivers. A blocked `receive()`
then raises `RuntimeError`, and a restart never delivers stale messages from the
previous session.

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
rejects conflicting duplicates, and expires incomplete assemblies. Its
`max_inflight_assemblies`, `max_inflight_bytes` and `max_completed_packets`
limits bound incomplete traffic and recent duplicate tracking globally.

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
python run_tests.py
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

When the optional dependency is installed, the real UDP loopback check can be
run with:

```bash
python -m unittest tests.mavlink.test_pymavlink_integration -v
```

GitHub Actions runs the hardware-free suite on Python 3.10 through 3.14, checks
the built wheel and runs this loopback test in a separate `pymavlink` job.

### Performance regression probe

The root-level benchmark exercises core model, synchronous and asynchronous
event, dependency, MAVLink and mission paths without opening hardware or
network connections:

```bash
python run_benchmarks.py --quick
python run_benchmarks.py --json > benchmark.json
```

Results are ordered from general primitives to domain-specific operations. The
median of five timed runs is reported as wall time, CPU time, ratio to a no-op
call, retained bytes per operation and peak bytes for one operation. Absolute
timings vary by machine; compare runs made with the same Python build and
hardware when checking a regression.

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

[python-shield]: https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white
[license-shield]: https://img.shields.io/github/license/TahsinCr/vehicle-autonomy-core.svg?style=for-the-badge

<!-- Links -->

[python-url]: https://www.python.org/downloads/
[readme-tr-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/README-TR.md
[changelog-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/CHANGELOG.md
[license-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/LICENSE
[copyright-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/COPYRIGHT
