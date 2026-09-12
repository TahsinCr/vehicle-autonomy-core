**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/mission.md)

# Mission orchestration

The mission module runs application-defined work while owning state transitions,
priority, prerequisites, conflicts, retries, timing and cleanup. Mission logic
stays in subclasses; the engine does not contain vehicle-specific behavior.

## Defining a mission

```python
from src.core import (
    Mission,
    MissionConflictPolicy,
    MissionPriority,
    MissionRetryPolicy,
)

class SurveyMission(Mission):
    priority = MissionPriority.NORMAL
    resources = frozenset({"navigation"})
    tags = frozenset({"survey"})
    conflict_policy = MissionConflictPolicy.QUEUE
    tick_interval = 0.1
    timeout_seconds = 120.0
    retry = MissionRetryPolicy(attempts=2, delay=1.0)

    def start(self) -> None:
        self.vehicle = ...

    def tick(self, elapsed_seconds: float) -> None:
        if self.finished():
            self.complete({"images": 24})

    def stop(self) -> None:
        self.vehicle.hold()
```

### Class configuration

| Attribute | Default | Meaning |
|---|---:|---|
| `priority` | `MissionPriority.NORMAL` | Smaller number means greater authority |
| `resources` | empty | Exclusively owned resource names |
| `blocks` | empty | Mission types this mission conflicts with |
| `tags` | empty | Selection labels for grouped control |
| `prerequisites` | empty | Mission types that must have succeeded |
| `conflict_policy` | `REJECT` | Reject, queue or preempt lower priority |
| `prerequisite_policy` | `REJECT` | Reject or queue while prerequisites are unmet |
| `tick_interval` | `0.1` | Seconds between ticks |
| `timeout_seconds` | `None` | Runtime timeout |
| `queue_timeout_seconds` | `None` | Maximum queued duration |
| `retry` | one attempt | `MissionRetryPolicy(attempts, delay)` |

`Mission(name=None)` creates a unique integer `id`; its default name is derived
from the class name and may be overridden per instance.

### Mission methods and properties

- Required: `start()`, `stop()`.
- Optional hooks: `pause()`, `resume()`, `tick(elapsed_seconds)`.
- Completion: `complete(result=None)`, `fail(reason, retryable=False)`.
- State: `id`, `name`, `control`, `runtime`, `stop_requested`.
- Engine wiring: `bind_control(control)` and `unbind_control(control)`; these
  are normally called by `MissionEngine`, not mission implementations.
- Reporting: `checkpoint(name, **values)`, `update_progress(value, reason="")`.
- Coordination: `wait_for_stop(timeout=None)`, `stop_missions(tags=(), resources=())`.

Calling `complete()`, `fail()`, self-targeted `stop()` or self-targeted
`cancel()` inside `start()`/`tick()` unwinds that callback. Terminal publication
and resource release occur after user code stops. If
`stop()` fails, the mission remains `STOPPING`, retains resources and raises
`MissionCleanupError`; retry the lifecycle operation after fixing the cause.

## `MissionEngine`

```text
MissionEngine(
    *,
    scheduler_interval=0.05,
    stop_timeout=2.0,
    event_history=1000,
    execution_history=256,
    max_active_missions=None,
    max_queued_missions=None,
    mission_factory=None,
    lifecycle=None,
    scheduler=None,
)
```

`mission_factory` constructs class references; the default calls the class with
no arguments. Supply a factory when mission constructors need dependencies.
Custom `MissionLifecycle` and `MissionScheduler` objects are bound to the engine.

### Registration and execution

| Method | Purpose |
|---|---|
| `register(mission)` | Register an existing instance |
| `unregister(mission)` | Remove an inactive mission; returns whether found |
| `mission(reference)` | Return the registered instance |
| `launch(reference, requester_id=None, reason="")` | Start or apply queue/conflict policy |
| `run(reference, ...)` | Register class/instance if needed, then launch |
| `launch_many(*missions)` | Launch several references |
| `run_parallel(*missions)` | Convenience parallel launch |
| `wait(reference, timeout=None)` | Wait for terminal state; `None` on timeout |

A mission reference may be a mission ID, registered instance, or mission class
where accepted by the operation.

### Lifecycle commands

`pause`, `resume`, `stop_mission` and `cancel` accept a mission reference plus
optional `requester_id` and `reason`. `complete`, `fail`, `progress` and
`checkpoint` update an explicitly selected mission. `stop_matching(requester_id,
tags=(), resources=())` allows a running mission to affect lower-authority work
without knowing concrete mission IDs.

If any terminal command or an uncaught worker error cannot clean up, the original
terminal phase, detached result, reason and retryability remain pending. This
applies to callback-driven and external lifecycle calls. The first terminal
intent wins; a conflicting command is rejected while it is pending. After fixing the cause,
`retry_cleanup(reference)` retries cleanup and commits the original intent.

`stop()` may be called again after an incomplete engine shutdown. Once mission
and scheduler cleanup succeeds, the stopping latch is cleared and the engine can
be started again. `close()` likewise retries event-channel shutdown before it
marks the engine closed or releases registered mission state; the engine remains
in stopping state between failed close attempts and rejects new work.

Only an active running requester may control another mission. Lower numeric
priority carries greater authority.

### State inspection

- `snapshot(reference) -> MissionSnapshot`
- `snapshots() -> tuple[MissionSnapshot, ...]`
- `manager_snapshot() -> MissionManagerSnapshot`
- `query_events(query=None) -> tuple[MissionEvent, ...]`
- `events` and `transitions` event buses
- `stopping` indicates that engine shutdown has begun.

Snapshots are immutable detached models. `MissionSnapshot` fields are:
`mission_id`, `name`, `phase`, `generation`, `attempt`, `progress`, `reason`,
`result`, `checkpoints`, `registered_at`, `queued_at`, `next_retry_at`,
`started_at`, `updated_at`, `finished_at`, `cleanup_pending`, and
`cleanup_error`. `evolve(**changes)` creates a
validated replacement; `duration_seconds` reports elapsed active duration when
enough timestamps are available.

## Chains

`MissionChain(chain_id, stages, stop_on_failure=True)` runs ordered stages. A
stage is a mission class, `MissionNode`, or `MissionParallelStage`.

```python
chain = MissionChain(
    "inspection",
    (
        TakeoffMission,
        MissionParallelStage(
            "inspect",
            (MissionNode("camera", CameraMission),
             MissionNode("mapping", MappingMission)),
            failure_policy=ParallelFailurePolicy.CANCEL_REMAINING,
        ),
        LandMission,
    ),
)

execution = engine.start_chain(
    chain,
    input={"altitude": 30},
    metadata={"operator": "station-1"},
)
finished = engine.wait_chain(execution.chain.chain_id, timeout=180.0)
```

Chain methods: `start_chain`, `chain_snapshot`, `wait_chain`, `stop_chain`,
`cancel_chain`, `forget_chain`. Execution results are passed through
`MissionExecutionContext`, whose fields are `chain_id`, `execution_id`,
`current_index`, `input`, `metadata`, `previous_mission`, `previous_result` and
`results`.

`MissionExecutionResult(node, mission_id, phase, result)` represents one stage.
A parallel stage result has `mission_id=None`, because it belongs to the named
group rather than whichever child finishes last.
`MissionChainSnapshot.current_stage` returns the active stage definition when
one exists. `MissionController.chain_context()` exposes the current immutable
chain context to a running mission.

## Parallel groups

```python
group = MissionParallelGroup(
    "preflight",
    (MissionNode("sensors", SensorCheck), MissionNode("link", LinkCheck)),
    failure_policy=ParallelFailurePolicy.WAIT_ALL,
)
snapshot = engine.start_parallel(group)
```

Methods: `start_parallel`, `parallel_snapshot`, `wait_parallel`,
`stop_parallel`, `cancel_parallel`, `forget_parallel`.

`MissionParallelSnapshot` contains `group`, `execution_id`, lifecycle flags,
`children`, `phases`, `results` and `reason`. Node names must be unique.

## Background missions

```python
background = engine.launch_background(
    HealthMonitorMission(),
    owner=chain_snapshot,
    termination_policy=OwnerTerminationPolicy.STOP_WITH_OWNER,
    failure_policy=BackgroundFailurePolicy.FAIL_OWNER,
)
```

The owner may be a mission, mission ID, chain snapshot or parallel snapshot.
`MissionBackgroundSnapshot` records `mission_id`, `owner_kind`, `owner_id`, both
policies, `active` and `phase`.

Owner termination policies:

- `STOP_WITH_OWNER`
- `CANCEL_WITH_OWNER`
- `KEEP_RUNNING`

Failure policies:

- `IGNORE`
- `FAIL_OWNER`
- `STOP_EXECUTION`

## Phases and policies

`MissionPhase` values: `REGISTERED`, `QUEUED`, `STARTING`, `RUNNING`,
`PAUSING`, `PAUSED`, `STOPPING`, `STOPPED`, `SUCCEEDED`, `FAILED`, `CANCELLED`.
Use `.active` and `.terminal` rather than duplicating phase sets.

`MissionPriority`: `CRITICAL=0`, `HIGH=100`, `NORMAL=500`, `LOW=900`,
`BACKGROUND=1000`. Custom integer priorities are allowed.

`MissionConflictPolicy`: `REJECT`, `QUEUE`, `PREEMPT_LOWER`.
`MissionPrerequisitePolicy`: `REJECT`, `QUEUE`.
`ParallelFailurePolicy`: `WAIT_ALL`, `CANCEL_REMAINING`, `STOP_REMAINING`.

`ensure_mission_transition(previous, current)` validates the public transition
table and raises `MissionTransitionError` for an invalid edge.

## Events

`MissionEvent` fields: `event_type`, `message`, `level`, `mission_id`,
`requester_id`, `generation`, `fields`, `sequence`, `timestamp`.

`MissionEventType`: `MANAGER`, `REGISTERED`, `UNREGISTERED`, `COMMAND`,
`TRANSITION`, `PROGRESS`, `CHECKPOINT`, `CHAIN`, `PARALLEL`, `BACKGROUND`,
`RETRY`, `LOG`, `ERROR`.

`MissionEventLevel`: `DEBUG=10`, `INFO=20`, `WARNING=30`, `ERROR=40`,
`CRITICAL=50`.

Filter retained events with `MissionEventQuery(mission_ids=frozenset(),
event_types=frozenset(), minimum_level=DEBUG, after_sequence=0, limit=200)`.

`MissionTransition` contains `mission_id`, `previous`, `current`, `requester_id`,
`reason` and `timestamp`. `MissionManagerSnapshot` reports running, registered,
active, queued and paused IDs plus current resource owners.

## Extension classes and errors

`MissionController` is the abstract command surface bound to a mission.
`MissionLifecycle` implements lifecycle operations and may be subclassed for a
different execution mechanism. `MissionScheduler` implements launch policy and
may be subclassed without changing mission classes.
Both extension components expose `bind(engine)` and are normally bound by the
engine constructor. `background_snapshot(mission_id)` inspects a registered
background relationship.

Errors:

- `MissionError`
- `MissionRegistrationError`
- `MissionPermissionError`
- `MissionConflictError`
- `MissionNotFoundError`
- `MissionTimeoutError`
- `MissionCleanupError`
- `MissionTransitionError`
