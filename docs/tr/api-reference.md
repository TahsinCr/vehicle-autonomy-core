[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/api-reference.md) | **Türkçe**

# Public API indeksi

Bu sayfa desteklenen public sembollerin temel envanteridir. Ayrıntılı parametre
anlamları ve örnekler ilgili modül rehberlerinde bulunur. `_` ile başlayan adlar
ve paketlerin `__all__` listelerinde bulunmayan semboller uygulama detayıdır.

## Kök paket: `src.core`

| Alan | Public semboller |
|---|---|
| Core | `Model`, `Service` |
| Dependency | `BaseDependencyContainer`, `DependencyContainer`, `DependencyCleanupPendingError`, `DependencyContainerClosedError`, `Inject`, `Lifetime`, `injection` |
| Events | `AsyncEventBus`, `AsyncEventBusActions`, `AsyncEventEngine`, `AsyncSubscription`, `CallbackTimeoutError`, `DeliveryMode`, `ErrorPolicy`, `EventBus`, `EventBusActions`, `EventBusStats`, `EventShutdownTimeoutError`, `EventEngine`, `EventFilter`, `EventErrorContext`, `EventTimeoutContext`, `MemoryEventHistory`, `PublishResult`, `Subscription` |
| Missions | `BackgroundFailurePolicy`, `Mission`, `MissionBackgroundSnapshot`, `MissionChain`, `MissionChainSnapshot`, `MissionConflictPolicy`, `MissionCleanupError`, `MissionController`, `MissionEvent`, `MissionEventLevel`, `MissionEventQuery`, `MissionEventType`, `MissionEngine`, `MissionExecutionContext`, `MissionExecutionResult`, `MissionLifecycle`, `MissionManagerSnapshot`, `MissionNode`, `MissionPhase`, `MissionPrerequisitePolicy`, `MissionPriority`, `MissionParallelGroup`, `MissionParallelSnapshot`, `MissionParallelStage`, `MissionSnapshot`, `MissionScheduler`, `OwnerTerminationPolicy`, `ParallelFailurePolicy` |

MAVLink sembolleri `src.core.mavlink` üzerinden alınır; böylece opsiyonel taşıma
bağımlılıkları kök API yüzeyine taşınmaz.

## `src.core.dependency`

Parametrelerin anlamı için [Dependency injection](dependency.md) rehberine bakın.

| Sembol | Tür / imza |
|---|---|
| `DependencyContainer` | sınıf `(*, parent=None, auto_wire=True)` |
| `BaseDependencyContainer` | sınıf `(*, container=None, parent=None, set_as_default=True, auto_wire=True)` |
| `Inject` | dataclass `(token=MISSING, optional=False)` |
| `Lifetime` | enum: `TRANSIENT`, `SINGLETON`, `SCOPED` |
| `injection` | fonksiyon `(target=None, *, container=None, dependencies=None, strict=False, **named_dependencies)` |
| `get_current_container` | fonksiyon `()` |
| `get_default_container` | fonksiyon `()` |
| `set_default_container` | fonksiyon `(container)` |
| `DependencyError` | temel exception |
| `DependencyNotFoundError` | exception |
| `DependencyResolutionError` | exception |
| `DependencyCleanupPendingError` | bekleyen resource cleanup exception'ı |
| `DependencyContainerClosedError` | terminal container exception'ı |
| `CircularDependencyError` | exception |
| `AsyncDependencyError` | exception |
| `Token` | type alias: hashable değer veya type |
| `DependencyMap` | parametre adından token'a eşleme alias'ı |
| `DEFAULT_PRIORITY` | integer sabiti, `100` |

`DependencyContainer` metotları: `register`, `singleton`, `scoped`, `transient`,
`instance`, `provider`, `resolve`, `resolve_async`, `build`, `build_async`,
`inject`, `create_scope`, `warmup`, `warmup_async`, `unregister`,
`unregister_async`, `shutdown`, `shutdown_async`, `has`, `can_resolve` ve
`registered_tokens` ve `closed` property’si.

## `src.core.events`

Callback ve concurrency semantiği için [Event'ler](events.md) rehberine bakın.

| Sembol | Constructor / görev |
|---|---|
| `BaseEventBus` | ortak history/filter yüzeyini tanımlayan abstract sınıf |
| `EventBus` | sync bus; `history`, `error_policy`, `executor`, replay/schedule/shutdown sınırları ve hook'lar |
| `AsyncEventBus` | async bus; `history`, `error_policy`, `delivery_mode`, replay/schedule sınırları ve async hook'lar |
| `EventEngine` | isimlendirilmiş sync kanallar |
| `AsyncEventEngine` | isimlendirilmiş async kanallar |
| `EventFilter` | `(event_type=None, predicate=None)` |
| `EventHistory` | abstract `append/query/latest/clear` deposu |
| `MemoryEventHistory` | `(capacity=1000)` |
| `Subscription` | iptal edilebilir sync kayıt |
| `AsyncSubscription` | iptal edilebilir async kayıt |
| `CallbackSubscription` | callback yürütme politikası ve hook'ları |
| `CallbackContext` | `(event, result=None, error=None, elapsed=0.0)` |
| `PublishResult` | `(matched=0, delivered=0, failed=0, errors=())` |
| `EventBusStats` | `(published=0, delivered=0, failed=0)` |
| `EventBusActions` | sync global hook'lar |
| `AsyncEventBusActions` | async global hook'lar |
| `EventErrorContext` | `(event, error)` |
| `EventTimeoutContext` | `(event_filter, timeout)` |
| `ErrorPolicy` | `ISOLATE`, `RAISE` |
| `DeliveryMode` | `SEQUENTIAL`, `CONCURRENT` |
| `EventBusError` | temel exception |
| `EventBusClosedError` | kapalı bus işlemi exception'ı |
| `InvalidEventHandlerError` | callback mode/type exception'ı |
| `CallbackTimeoutError` | callback zaman bütçesi exception'ı |
| `EventShutdownTimeoutError` | periyodik iş kapanış exception'ı |

Bus işlemleri: `subscribe`, `once`, `publish`, `wait_for`, `query`, `latest`,
`publish_every`, `clear`, `close`. Async bus ayrıca `publish_threadsafe` sunar.

## `src.core.mission`

Durum ve sahiplik kuralları için [Mission orkestrasyonu](mission.md) rehberine bakın.

| Grup | Public semboller |
|---|---|
| Motor | `MissionEngine`, `MissionLifecycle`, `MissionScheduler`, `MissionController` |
| Tanımlar | `Mission`, `MissionNode`, `MissionChain`, `MissionParallelGroup`, `MissionParallelStage`, `MissionRetryPolicy` |
| Snapshot'lar | `MissionSnapshot`, `MissionManagerSnapshot`, `MissionChainSnapshot`, `MissionParallelSnapshot`, `MissionBackgroundSnapshot`, `MissionExecutionContext`, `MissionExecutionResult` |
| Event'ler | `MissionEvent`, `MissionEventQuery`, `MissionTransition` |
| Durum | `MissionPhase`, `MissionPriority`, `MissionEventLevel`, `MissionEventType` |
| Politikalar | `MissionConflictPolicy`, `MissionPrerequisitePolicy`, `ParallelFailurePolicy`, `OwnerTerminationPolicy`, `BackgroundFailurePolicy` |
| Doğrulama | `ensure_mission_transition` |
| Hatalar | `MissionError`, `MissionRegistrationError`, `MissionPermissionError`, `MissionConflictError`, `MissionNotFoundError`, `MissionTimeoutError`, `MissionCleanupError`, `MissionTransitionError` |

Model constructor alanları ve `retry_cleanup` dahil motor işlemleri mission
rehberinde açıklanır.

## `src.core.mavlink`

[MAVLink](mavlink.md) ve [Uygulama protokolü](application-protocol.md)
rehberlerine bakın.

| Grup | Public semboller |
|---|---|
| Runtime | `MavlinkRuntime`, `AsyncMavlinkRuntime`, `MavlinkRuntimeState`, `MavlinkRuntimeError`, `MavlinkAction` |
| Taşıma | `MavlinkEndpoint`, `MavlinkConnection`, `MavlinkClient`, `MavlinkMessageRouter`, `MavlinkAsyncChannel`, `MavlinkUnavailableError` |
| Mesaj routing | `MavlinkMessageFilter`, `MavlinkMessageEnvelope`, `MavlinkIngressFilter`, `MavlinkRouterStats`, `MavlinkRouterError`, `MavlinkHeader`, `MavlinkMessage` |
| Araçlar | `MavlinkCollection`, `MavlinkVehicle`, `MavlinkComponent`, `MavlinkVehicleState`, `AsyncMavlinkCollection`, `AsyncMavlinkVehicle`, `AsyncMavlinkComponent` |
| Cache/history | `MessageCache`, `MessageCacheStats`, `MessageHistory`, `SqliteMessageHistory`, `MessageRecord`, `HistoryWriterStats` |
| Uygulama paketleri | `MavlinkApplicationPacket`, `MavlinkApplicationCodec`, `MavlinkApplicationAssembler`, `MavlinkApplicationChannel`, `MavlinkApplicationProtocolError` |
| Peer | `MavlinkApplicationPeer`, `MavlinkApplicationPeerState`, `MavlinkApplicationResponse` |
| Dispatch | `MavlinkApplicationDispatcher`, `MavlinkApplicationHandlerRegistry`, `MavlinkApplicationHandler`, `MavlinkApplicationResult`, `MavlinkApplicationDispatch` |
| Remote log | `MavlinkRemoteLogLevel`, `MavlinkRemoteLogRecord`, `MavlinkRemoteLogBatch` |

Sabitler: `DEFAULT_APPLICATION_NETWORK`, `DEFAULT_APPLICATION_MESSAGE_TYPE`,
`REMOTE_LOG_PROTOCOL_VERSION`, `REMOTE_LOG_PACKET_TYPE`,
`REMOTE_LOG_MAX_BATCH_RECORDS`, `REMOTE_LOG_MAX_BATCH_BYTES` ve
`REMOTE_LOG_MAX_DETAILS_BYTES`.

## Kararlılık kuralları

- Export edilen semboller ve belgelenmiş parametreler desteklenen public yüzeydir.
- `_` ile başlayan constructor parametreleri görülebilse de uygulama detayıdır.
- Snapshot dataclass'larına minor sürümlerde varsayılanlı alanlar eklenebilir.
- Yeni enum üyeleri ve opsiyonel parametreler geriye uyumlu biçimde eklenebilir.
- Cleanup, sıralama, timeout ve callback thread davranışları API sözleşmesidir.
