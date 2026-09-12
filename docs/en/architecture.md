**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/architecture.md)

# Architecture

## Module boundaries

| Module | Responsibility | Does not own |
|---|---|---|
| `abstracts` | Common model serialization and service lifecycle | Application policy |
| `dependency` | Object construction, scopes and disposal | Global business state |
| `events` | In-process sync/async delivery | MAVLink transport |
| `mission` | Mission state, authority and orchestration | Vehicle-specific actions |
| `mavlink` | Transport, routing, vehicle views and app packets | UI severity or mission logic |

Higher-level application code composes these modules. Mission implementations
may receive a MAVLink runtime through dependency injection, but the mission
package does not import vehicle-specific behavior.

## Ownership model

- A `DependencyContainer` owns cached objects it creates or receives as instances.
- An `EventBus` owns subscriptions and periodic schedules registered on it.
- A `MavlinkRuntime` owns its client, router, vehicle registry, callback delivery
  and optional application-protocol components.
- A `MessageHistory` attached with `add_history()` remains caller-owned.
- A `MissionEngine` owns registered mission runtime state and worker threads.

Use context managers wherever possible. Caller-owned objects should be closed
outside the owner that consumes them:

```python
with MessageHistory(background=True) as history:
    with MavlinkRuntime(endpoint) as link:
        link.add_history(history)
```

## Concurrency model

### Events

`EventBus` invokes synchronous subscribers in the publishing thread unless an
executor is configured. `AsyncEventBus` invokes coroutine subscribers on its
owning event loop. Replay establishes a boundary: events published during replay
are delivered after replay and cannot overtake it.

### MAVLink

One router receive thread reads each MAVLink connection. Source/type filtering
and ingress filters run on this hot path. Keep them deterministic and fast.
Runtime callback delivery is bounded so slow consumers cannot create unlimited
memory growth. Async runtime transport calls use owned worker operations; task
cancellation does not detach an already-started blocking operation.

### Missions

The scheduler coordinates launches. A mission worker executes `start()` and
periodic `tick()` calls. Lifecycle commands are serialized, and resources are
released only after mission callback code has unwound and cleanup succeeds.

### Dependencies

Singleton and scoped initialization gates prevent duplicate construction.
Circular resolution is detected across threads and independent asyncio tasks.
Disposal calls user code outside registration locks and claims each instance so
concurrent cleanup paths cannot close it twice.

## Error philosophy

- Invalid configuration fails at construction time.
- Subscriber errors are isolated by default and reported in `PublishResult`.
- Cleanup attempts all owned resources and preserves every failure.
- Bounded queues report overflow rather than silently claiming complete delivery.
- Timeouts do not forcibly terminate Python threads or user callbacks.
- Snapshot/state objects expose errors without requiring log parsing.

## Extension points

Prefer the narrowest supported extension:

- subclass `Model` for serializable domain snapshots;
- subclass `BaseDependencyContainer` for an application composition root;
- implement `EventHistory` for another event store;
- subclass `Mission` and optionally `MissionLifecycle`/`MissionScheduler`;
- subclass `MessageHistory` for another telemetry store;
- inject a custom MAVLink connection, router, peer or dispatcher when transport
  behavior truly differs.
