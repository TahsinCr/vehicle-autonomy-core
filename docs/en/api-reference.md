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

## Stability rules

- Exported symbols and documented parameters form the supported public surface.
- Underscore-prefixed constructor parameters are internal even if inspectable.
- Snapshot dataclasses may gain fields with defaults in minor releases.
- New enum members and new optional parameters may be added without breaking
  existing callers.
- Cleanup, ordering, timeout and callback-thread behavior are part of the API
  contract, not merely implementation details.
