**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/api-reference.md)

# Public API index

This page is the canonical inventory of supported public symbols. Detailed
parameters and examples are linked by module. Names beginning with `_` and
symbols not exported through a package `__all__` are implementation details.

## Root package: `src.core`

The root package provides the common, dependency, event and mission APIs:

| Area | Public symbols |
|---|---|
| Core | `Model`, `Service` |
| Dependency | `BaseDependencyContainer`, `DependencyContainer`, `DependencyCleanupPendingError`, `DependencyContainerClosedError`, `Inject`, `Lifetime`, `injection` |
| Events | `AsyncEventBus`, `AsyncEventBusActions`, `AsyncEventEngine`, `AsyncSubscription`, `CallbackTimeoutError`, `DeliveryMode`, `ErrorPolicy`, `EventBus`, `EventBusActions`, `EventBusStats`, `EventShutdownTimeoutError`, `EventEngine`, `EventFilter`, `EventErrorContext`, `EventTimeoutContext`, `MemoryEventHistory`, `PublishResult`, `Subscription` |
| Missions | `BackgroundFailurePolicy`, `Mission`, `MissionBackgroundSnapshot`, `MissionChain`, `MissionChainSnapshot`, `MissionConflictPolicy`, `MissionCleanupError`, `MissionController`, `MissionEvent`, `MissionEventLevel`, `MissionEventQuery`, `MissionEventType`, `MissionEngine`, `MissionExecutionContext`, `MissionExecutionResult`, `MissionLifecycle`, `MissionManagerSnapshot`, `MissionNode`, `MissionPhase`, `MissionPrerequisitePolicy`, `MissionPriority`, `MissionParallelGroup`, `MissionParallelSnapshot`, `MissionParallelStage`, `MissionSnapshot`, `MissionScheduler`, `OwnerTerminationPolicy`, `ParallelFailurePolicy` |

MAVLink symbols are imported from `src.core.mavlink`, keeping optional transport
dependencies out of the root surface.

## `src.core.dependency`

See [Dependency injection](dependency.md) for parameter semantics.

| Symbol | Kind / signature |
|---|---|
| `DependencyContainer` | class `(*, parent=None, auto_wire=True)` |
| `BaseDependencyContainer` | class `(*, container=None, parent=None, set_as_default=True, auto_wire=True)` |
| `Inject` | dataclass `(token=MISSING, optional=False)` |
| `Lifetime` | enum: `TRANSIENT`, `SINGLETON`, `SCOPED` |
| `injection` | function `(target=None, *, container=None, dependencies=None, strict=False, **named_dependencies)` |
| `get_current_container` | function `()` |
| `get_default_container` | function `()` |
| `set_default_container` | function `(container)` |
| `DependencyError` | base exception |
| `DependencyNotFoundError` | exception |
| `DependencyResolutionError` | exception |
| `DependencyCleanupPendingError` | pending resource cleanup exception |
| `DependencyContainerClosedError` | terminal container exception |
| `CircularDependencyError` | exception |
| `AsyncDependencyError` | exception |
| `Token` | type alias: hashable or type |
| `DependencyMap` | parameter-name-to-token mapping alias |
| `DEFAULT_PRIORITY` | integer constant, `100` |

`DependencyContainer` methods: `register`, `singleton`, `scoped`, `transient`,
`instance`, `provider`, `resolve`, `resolve_async`, `build`, `build_async`,
`inject`, `create_scope`, `warmup`, `warmup_async`, `unregister`,
`unregister_async`, `shutdown`, `shutdown_async`, `has`, `can_resolve`, and
`registered_tokens`, and the `closed` property.

## `src.core.events`

See [Events](events.md) for callback and concurrency semantics.

| Symbol | Constructor / role |
|---|---|
| `BaseEventBus` | abstract shared history/filter surface |
| `EventBus` | sync bus; `history`, `error_policy`, `executor`, replay/schedule/shutdown limits and hooks |
| `AsyncEventBus` | async bus; `history`, `error_policy`, `delivery_mode`, replay/schedule limits and async hooks |
| `EventEngine` | named sync channels |
| `AsyncEventEngine` | named async channels |
| `EventFilter` | `(event_type=None, predicate=None)` |
| `EventHistory` | abstract `append/query/latest/clear` store |
| `MemoryEventHistory` | `(capacity=1000)` |
| `Subscription` | cancellable sync registration |
| `AsyncSubscription` | cancellable async registration |
| `CallbackSubscription` | callback execution policy and hooks |
| `CallbackContext` | `(event, result=None, error=None, elapsed=0.0)` |
| `PublishResult` | `(matched=0, delivered=0, failed=0, errors=())` |
| `EventBusStats` | `(published=0, delivered=0, failed=0)` |
| `EventBusActions` | sync global hooks |
| `AsyncEventBusActions` | async global hooks |
| `EventErrorContext` | `(event, error)` |
| `EventTimeoutContext` | `(event_filter, timeout)` |
| `ErrorPolicy` | `ISOLATE`, `RAISE` |
| `DeliveryMode` | `SEQUENTIAL`, `CONCURRENT` |
| `EventBusError` | base exception |
| `EventBusClosedError` | closed-operation exception |
| `InvalidEventHandlerError` | callback-mode/type exception |
| `CallbackTimeoutError` | callback budget exception |
| `EventShutdownTimeoutError` | periodic shutdown exception |

Bus operations: `subscribe`, `once`, `publish`, `wait_for`, `query`, `latest`,
`publish_every`, `clear`, `close`. Async bus additionally exposes
`publish_threadsafe`.

## `src.core.mission`

See [Mission orchestration](mission.md) for state and ownership rules.

| Group | Public symbols |
|---|---|
| Engine | `MissionEngine`, `MissionLifecycle`, `MissionScheduler`, `MissionController` |
| Definitions | `Mission`, `MissionNode`, `MissionChain`, `MissionParallelGroup`, `MissionParallelStage`, `MissionRetryPolicy` |
| Snapshots | `MissionSnapshot`, `MissionManagerSnapshot`, `MissionChainSnapshot`, `MissionParallelSnapshot`, `MissionBackgroundSnapshot`, `MissionExecutionContext`, `MissionExecutionResult` |
| Events | `MissionEvent`, `MissionEventQuery`, `MissionTransition` |
| State | `MissionPhase`, `MissionPriority`, `MissionEventLevel`, `MissionEventType` |
| Policies | `MissionConflictPolicy`, `MissionPrerequisitePolicy`, `ParallelFailurePolicy`, `OwnerTerminationPolicy`, `BackgroundFailurePolicy` |
| Validation | `ensure_mission_transition` |
| Errors | `MissionError`, `MissionRegistrationError`, `MissionPermissionError`, `MissionConflictError`, `MissionNotFoundError`, `MissionTimeoutError`, `MissionCleanupError`, `MissionTransitionError` |

Model constructor fields and every engine operation, including
`retry_cleanup`, are listed in the mission guide.

`MissionNode(name, mission)`, `MissionChain(chain_id, stages,
stop_on_failure=True)`, `MissionParallelStage(name, nodes, failure_policy)` and
`MissionParallelGroup(group_id, nodes, failure_policy)` accept configured
mission instances, never mission classes.
Their `to_dict()` output replaces each executable mission object with an
`id`/`name`/`type` descriptor. `MissionEngine.run()` rejects duplicate instance
IDs before admitting any input.

## `src.core.mavlink`

See [MAVLink](mavlink.md) and [Application protocol](application-protocol.md).

| Group | Public symbols |
|---|---|
| Runtime | `MavlinkRuntime`, `AsyncMavlinkRuntime`, `MavlinkRuntimeState`, `MavlinkRuntimeError`, `MavlinkAction` |
| Transport | `MavlinkEndpoint`, `MavlinkConnection`, `MavlinkClient`, `MavlinkMessageRouter`, `MavlinkAsyncChannel`, `MavlinkUnavailableError` |
| Message routing | `MavlinkMessageFilter`, `MavlinkMessageEnvelope`, `MavlinkIngressFilter`, `MavlinkRouterStats`, `MavlinkRouterError`, `MavlinkHeader`, `MavlinkMessage` |
| Vehicles | `MavlinkCollection`, `MavlinkVehicle`, `MavlinkComponent`, `MavlinkVehicleState`, `AsyncMavlinkCollection`, `AsyncMavlinkVehicle`, `AsyncMavlinkComponent` |
| Cache/history | `MessageCache`, `MessageCacheStats`, `MessageHistory`, `SqliteMessageHistory`, `MessageRecord`, `HistoryWriterStats` |
| Application packets | `MavlinkApplicationPacket`, `MavlinkApplicationCodec`, `MavlinkApplicationAssembler`, `MavlinkApplicationChannel`, `MavlinkApplicationProtocolError` |
| Peer | `MavlinkApplicationPeer`, `MavlinkApplicationPeerState`, `MavlinkApplicationResponse` |
| Dispatch | `MavlinkApplicationDispatcher`, `MavlinkApplicationHandlerRegistry`, `MavlinkApplicationHandler`, `MavlinkApplicationResult`, `MavlinkApplicationDispatch` |
| Remote logs | `MavlinkRemoteLogLevel`, `MavlinkRemoteLogRecord`, `MavlinkRemoteLogBatch` |

Constants: `DEFAULT_APPLICATION_NETWORK`, `DEFAULT_APPLICATION_MESSAGE_TYPE`,
`REMOTE_LOG_PROTOCOL_VERSION`, `REMOTE_LOG_PACKET_TYPE`,
`REMOTE_LOG_MAX_BATCH_RECORDS`, `REMOTE_LOG_MAX_BATCH_BYTES`, and
`REMOTE_LOG_MAX_DETAILS_BYTES`.

## Callable reference

The tables below are the quick contract. Module guides explain the same calls
in context and contain complete examples.

### Dependency operations

| Call | Parameters | Return and behavior |
|---|---|---|
| `register` | `token/provider`; one of `abstract`, `concrete`, `factory`, `instance`; `lifetime`, `dependencies`, `priority` | Registers one provider and returns the container. Replacing a cached provider disposes the old value first. |
| `singleton` | Registration parameters; ready `instance` is allowed | One cached value at the provider-owning container. |
| `scoped` | Registration parameters except ready instance | One cached value in each resolving scope. |
| `transient` | Registration parameters except ready instance | New caller-owned value for every resolution. |
| `instance` | `token`, ready `instance`, optional `abstract/priority` | Registers a container-owned ready singleton. |
| `provider` | `token/abstract`, `lifetime`, `dependencies`, `priority` | Decorator; preserves and returns the decorated factory/class. |
| `resolve` / `resolve_async` | `token` | Resolves one value. Use async for coroutine providers or `aclose()` ownership. |
| `build` / `build_async` | `factory`, optional dependency overrides | Constructs a transient value without registering it. |
| `inject` / `injection` | target, container/dependency overrides, `strict`, named tokens | Decorates a class or callable; explicit caller arguments always win. |
| `has` | `token` | Whether a registration is visible through the parent chain. |
| `can_resolve` | `token` | Whether resolution is currently admissible, including lifecycle state. |
| `registered_tokens` | none | Immutable tuple of locally registered tokens. |
| `create_scope` | none | Child container; scoped values belong to it, parent singletons remain parent-owned. |
| `warmup` / `warmup_async` | optional tokens and lifetimes | Eagerly resolves in ascending priority order. |
| `unregister` / `unregister_async` | `token` | Removes the registration and closes unreferenced cached values exactly once. |
| `shutdown` / `shutdown_async` | none | Terminal reverse-order cleanup. Failed resources remain owned for retry. |

Cleanup re-entry into its own unregister or shutdown attempt raises
`DependencyResolutionError`; independent concurrent callers still share the
active attempt.

### Event operations

Filter arguments are mutually composable: `event_filter`, `event_type`, and a
synchronous `predicate`. Passing incompatible duplicate filter forms raises
`ValueError`.

| Call | Parameters | Return and behavior |
|---|---|---|
| `subscribe` | callback, filters, `once`, `times`, `replay` | Cancellable subscription. `times` counts accepted deliveries, not publications. |
| `once` | callback, filters, `replay` | Shortcut for one accepted delivery. |
| `publish` | event | `PublishResult`; sync delivery runs on publisher/executor, async delivery follows `DeliveryMode`. |
| `wait_for` | filters, optional `timeout` | Matching event or `None`; temporary subscription is always removed. |
| `latest` | filters | Latest retained match or `None`; requires configured history. |
| `query` | filters, optional `limit` | Oldest-first immutable tuple from retained history. |
| `publish_every` | event, positive `interval`, optional `times/immediately` | Owned periodic subscription; cancellation stops future publication. |
| `publish_threadsafe` | event | Async bus only; concurrent future scheduled on the owning loop. |
| `clear` | none | Cancels subscribers but keeps the bus reusable. |
| `close` | none | Permanently closes subscriptions and owned schedules. Async close is awaited. |
| `EventEngine.channel` | normalized channel name | Returns or lazily creates a channel with engine defaults. |
| `add/remove` | channel name and bus | Installs/removes an explicitly owned named bus. |

### Mission operations

`MissionReference` means a `Mission` instance or integer mission ID for lookup
and lifecycle commands. Execution accepts a configured instance.

| Call | Parameters | Return and behavior |
|---|---|---|
| `register` | mission instance | Binds control and returns its initial snapshot. |
| `run` | one or more mission instances, optional requester/reason | Independently admits each instance. Returns one snapshot for one input, otherwise a tuple. |
| `run_parallel` | `MissionParallelGroup` | Starts one aggregate group with child/result ownership. |
| `run_chain` | `MissionChain`, optional JSON-safe `input/metadata` | Starts an isolated ordered execution. |
| `run_background` | mission, owner, termination/failure policies | Attaches work to a mission, chain or parallel owner. |
| `pause/resume` | reference, requester/reason | Performs an authorized lifecycle transition. |
| `stop_mission/cancel` | reference, requester/reason | Requests terminal cleanup; cancel and stop retain distinct final phases. |
| `complete/fail` | reference, result or reason/retryable | Commits terminal intent after callback exit and cleanup. |
| `progress/checkpoint` | reference and detached values | Updates observable state; terminal missions reject updates. |
| `retry_cleanup` | reference | Retries a stored terminal intent after cleanup failure. |
| `wait` | reference, optional timeout | Terminal snapshot or `None`. |
| `snapshot/snapshots/manager_snapshot` | optional reference | Immutable current state views. |
| `query_events` | optional `MissionEventQuery` | Oldest-first retained mission events. |
| `stop_matching` | running requester ID, tags/resources | Stops matching lower-authority missions. |
| `unregister` | inactive reference | Removes and unbinds a mission; returns whether it existed. |

Chain and parallel families use the consistent verbs `snapshot`, `wait`,
`stop`, `cancel`, and `forget`. `forget` only removes retained terminal
execution data; it does not stop active work.

### MAVLink runtime operations

| Call | Parameters | Return and behavior |
|---|---|---|
| `start/stop/reconnect/close` | none | Own transport in dependency order. `close` is terminal; stop permits restart. Async variants are awaited. |
| `subscribe/once` | message type/filter, callback, predicate and callback policy options | Delivers outside the reader thread through bounded runtime delivery. Supports decorator form. |
| `wait_for` | message types/filter, predicate, timeout, optional sequence boundary | Waits for a future matching message; raises timeout where documented by the transport layer. |
| `latest` | optional type/filter | Returns the latest cached live message without waiting. |
| `add_filter` | synchronous ingress predicate | Rejects traffic before cache, discovery, history and subscribers; returns a cancellable registration. |
| `add_history` | caller-owned `MessageHistory` | Records future envelopes until the returned subscription is cancelled. Runtime never closes storage. |
| `send/send_named` | encoded message or message name/fields | Serialized transport send. |
| `prune_vehicles` | optional age override | Removes eligible disconnected vehicle/component state; returns removal count. |
| `on/on_start/on_stop/on_error` | action name/callback plus callback policy | Registers repeatable lifecycle actions; decorator form is supported. |
| `handle` | packet type, handler, `replace` | Registers an application request handler. Requires application configuration. |
| `notify` | packet type and JSON-safe payload | Sends a packet without waiting for a response. |
| `request` | packet type/payload, accepted response types, timeout | Sends a correlated request and waits for its response. |

### Vehicle and component operations

| Call | Scope and behavior |
|---|---|
| `vehicles.wait_for(timeout=...)` | Wait for any connected vehicle; async collection awaits it. |
| `vehicles.get(system_id)` | Lookup only; never creates a remote endpoint. |
| `vehicles.get_component(component_id)` | All currently known matching components across vehicles. |
| `vehicle.get_component(id)` / `get_components()` | Lookup one or snapshot all components for that vehicle. |
| `vehicle.wait_for_component(timeout=...)` | Wait for any component belonging to the vehicle. |
| `latest/history/wait_for/subscribe` | Automatically constrain telemetry to the selected system/component. |
| `send/send_named/request_message_rate` | Automatically target the selected system/component. |
| `notify/request/handle` | Source-scoped application protocol operations. |
| `on_connected/on_disconnected/on_error` | Repeatable scope lifecycle callbacks. |
| `on_component_*` | Vehicle-level component discovery/lifecycle callbacks. |

### Cache and history operations

| Call | Parameters | Behavior |
|---|---|---|
| `MessageCache.add` | key and value | Appends to bounded per-key history and updates latest. |
| `latest/all/snapshot/keys/stats` | key or none | Read current retained data without exposing mutable internal collections. |
| `MessageHistory.append` | `MavlinkMessageEnvelope` | Creates a detached JSON-safe record; optional writer moves serialization off caller thread. |
| `query/latest` | system/component/type/time filters and limit | Indexed filtering with immutable result tuples. |
| `flush` | timeout | Waits for background writer durability and surfaces stored failure. |
| `clear` | none | Removes persisted records while leaving storage usable. |
| `close` | none | Flushes and closes owned writer/storage; idempotent after success. |

`SqliteMessageHistory` adds `path`, `wal` and `busy_timeout`. `limit=None`
means unbounded retention; bounded production deployments should choose an
explicit limit and queue capacity.

## Stability rules

- Exported symbols and documented parameters form the supported public surface.
- Underscore-prefixed constructor parameters are internal even if inspectable.
- Snapshot dataclasses may gain fields with defaults in minor releases.
- New enum members and new optional parameters may be added without breaking
  existing callers.
- Cleanup, ordering, timeout and callback-thread behavior are part of the API
  contract, not merely implementation details.
