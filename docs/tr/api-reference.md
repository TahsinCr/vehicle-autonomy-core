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

`MissionNode(name, mission)`, `MissionChain(chain_id, stages,
stop_on_failure=True)`, `MissionParallelStage(name, nodes, failure_policy)` ve
`MissionParallelGroup(group_id, nodes, failure_policy)` yapılandırılmış mission
instance'ları kabul eder; mission class kabul etmez.
Bu modellerin `to_dict()` çıktısı executable mission nesnesini
`id`/`name`/`type` descriptor'ıyla değiştirir. `MissionEngine.run()`, herhangi
bir girdiyi başlatmadan önce duplicate instance ID'lerini reddeder.

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

## Çağrılabilir API referansı

Bu tablolar hızlı sözleşmedir. Modül rehberleri aynı işlemleri gerçekçi
örnekler, lifecycle ve hata davranışlarıyla açıklar.

### Dependency işlemleri

| Çağrı | Parametreler | Dönüş ve davranış |
|---|---|---|
| `register` | `token/provider`; `abstract`, `concrete`, `factory`, `instance` kaynaklarından biri; `lifetime`, `dependencies`, `priority` | Provider kaydeder ve container'ı döndürür. Replacement eski cache'i önce kapatır. |
| `singleton` | Registration parametreleri; hazır `instance` olabilir | Provider sahibi container'da tek cache. |
| `scoped` | Hazır instance dışındaki registration parametreleri | Resolution yapan scope başına tek cache. |
| `transient` | Hazır instance dışındaki registration parametreleri | Her resolution'da yeni, caller-owned nesne. |
| `instance` | `token`, hazır nesne, opsiyonel `abstract/priority` | Container-owned hazır singleton kaydeder. |
| `provider` | token, lifetime, dependency override ve priority | Factory/class decorator'ı; decorate edilen nesneyi korur. |
| `resolve` / `resolve_async` | `token` | Tek değer çözer. Coroutine provider veya `aclose()` sahipliğinde async kullanılır. |
| `build` / `build_async` | factory ve opsiyonel dependency mapping | Kayıt oluşturmadan transient nesne kurar. |
| `inject` / `injection` | target, container/dependency override, `strict`, named token'lar | Eksik argümanları çözer; caller'ın verdiği argümanı değiştirmez. |
| `has` / `can_resolve` | token | Görünür registration'ı / lifecycle dahil gerçek resolution olanağını bildirir. |
| `registered_tokens` | yok | Yalnızca local token'ları immutable tuple verir. |
| `create_scope` | yok | Scoped değerlerin sahibi child container oluşturur. |
| `warmup` / `warmup_async` | opsiyonel token ve lifetime'lar | Artan priority sırasında eager resolution yapar. |
| `unregister` / `unregister_async` | token | Kaydı siler, sahipsiz cache'i tam bir kez kapatır. |
| `shutdown` / `shutdown_async` | yok | Ters sıralı terminal cleanup; başarısız kaynak retry için sahiplikte kalır. |

Cleanup'ın kendi unregister veya shutdown girişimine yeniden girmesi
`DependencyResolutionError` üretir; bağımsız eşzamanlı çağrılar aktif girişimi
paylaşmayı sürdürür.

### Event işlemleri

| Çağrı | Parametreler | Dönüş ve davranış |
|---|---|---|
| `subscribe` | callback, filter'lar, `once`, `times`, `replay` | İptal edilebilir subscription; `times` publication değil kabul edilen delivery sayısıdır. |
| `once` | callback, filter'lar, replay | Bir kabul edilen delivery için kısayol. |
| `publish` | event | `PublishResult`; sync caller/executor'da, async seçilen `DeliveryMode` ile teslim eder. |
| `wait_for` | filter'lar ve timeout | Eşleşen event veya `None`; geçici subscription her durumda kaldırılır. |
| `latest/query` | filter'lar ve opsiyonel limit | Configured history'den son kaydı veya oldest-first tuple'ı verir. |
| `publish_every` | event, pozitif interval, `times/immediately` | Bus-owned periyodik subscription oluşturur. |
| `publish_threadsafe` | event | Yalnızca async bus; owner loop'a planlanan concurrent future döndürür. |
| `clear` / `close` | yok | Subscriber'ları temizler / bus'ı owned schedule'larla kalıcı kapatır. |
| `EventEngine.channel` | normalize edilen isim | Engine default'larıyla kanalı döndürür veya lazy oluşturur. |
| `add/remove` | kanal adı ve bus | Açıkça yapılandırılmış named bus ekler/kaldırır. |

### Mission işlemleri

`MissionReference`, lookup ve lifecycle komutları için instance veya integer
ID'dir. Çalıştırma hazır bir instance kabul eder.

| Çağrı | Parametreler | Dönüş ve davranış |
|---|---|---|
| `register` | mission instance | Control bağlar ve ilk snapshot'ı döndürür. |
| `run` | bir veya daha fazla mission instance, requester/reason | Her instance'ı bağımsız admission'a alır. Tek girişte snapshot, çoklu girişte tuple döndürür. |
| `run_parallel` | `MissionParallelGroup` | Child ve sonuç sahipliği olan aggregate grup başlatır. |
| `run_chain` | chain, JSON-safe input/metadata | İzole sıralı execution başlatır. |
| `run_background` | mission, owner ve iki policy | Mission/chain/parallel owner'a background iş bağlar. |
| `pause/resume` | reference, requester/reason | Yetkilendirilmiş lifecycle transition uygular. |
| `stop_mission/cancel` | reference, requester/reason | Terminal cleanup ister; final phase'leri farklıdır. |
| `complete/fail` | reference, result veya reason/retryable | Callback çıkışı ve cleanup sonrası terminal intent'i commit eder. |
| `progress/checkpoint` | reference ve ayrık değerler | Observable state'i günceller; terminal mission reddeder. |
| `retry_cleanup` | reference | Cleanup hatasından sonra saklanan terminal intent'i yeniden dener. |
| `wait` | reference/timeout | Terminal snapshot veya `None`. |
| `snapshot/snapshots/manager_snapshot` | opsiyonel reference | Immutable anlık durumlar. |
| `query_events` | opsiyonel query | Oldest-first retained mission event'leri. |
| `stop_matching` | running requester ID, tag/resource | Eşleşen düşük yetkili mission'ları durdurur. |
| `unregister` | inactive reference | Mission'ı silip control'ü ayırır; bulunma durumunu döndürür. |

Chain ve parallel aileleri `snapshot`, `wait`, `stop`, `cancel`, `forget`
fiillerini kullanır. `forget` yalnızca terminal history'yi siler; aktif işi durdurmaz.

### MAVLink runtime işlemleri

| Çağrı | Parametreler ve davranış |
|---|---|
| `start/stop/reconnect/close` | Transport'u dependency sırasıyla yönetir. `close` terminaldir; `stop` restart'a izin verir. Async karşılıklar await edilir. |
| `subscribe/once` | Type/filter, callback, predicate ve callback policy alır; decorator olabilir. Bounded delivery reader thread'i korur. |
| `wait_for` | Type/filter, predicate, timeout ve opsiyonel sequence boundary ile gelecekteki mesajı bekler. |
| `latest` | Beklemeden en son cached live mesajı verir. |
| `add_filter` | Sync ingress predicate'i cache, discovery, history ve delivery öncesinde çalıştırır. |
| `add_history` | Caller-owned history'ye gelecekteki envelope'ları kaydeder; runtime storage'ı kapatmaz. |
| `send/send_named` | Hazır mesajı veya ad/field ile mesajı serialized transport'tan yollar. |
| `prune_vehicles` | Uygun disconnected state'i siler ve sayıyı döndürür. |
| `on/on_start/on_stop/on_error` | Tekrarlanabilir lifecycle callback'i; decorator formu desteklenir. |
| `handle/notify/request` | Application handler, tek yönlü paket ve correlated request/response işlemleri. |

### Araç, component, cache ve history

| Çağrı | Davranış |
|---|---|
| `vehicles.wait_for/get` | Herhangi bir bağlı aracı bekler / ID ile yalnızca lookup yapar. |
| `vehicles.get_component` | Tüm araçlardaki eşleşen component'leri verir. |
| `vehicle.get_component/get_components/wait_for_component` | Seçilen araç içindeki component'leri sorgular. |
| Scope `latest/history/wait_for/subscribe` | System/component filtresini otomatik uygular. |
| Scope `send/send_named/request_message_rate` | Hedef system/component bilgisini otomatik uygular. |
| `MessageCache.add/latest/all/snapshot/keys/stats` | Bounded per-key state'i mutable internal collection sızdırmadan yönetir. |
| `MessageHistory.append/query/latest` | Detached JSON-safe kayıt oluşturur ve source/type/time ile filtreler. |
| `flush/clear/close` | Writer durability bekler, kayıtları temizler veya storage'ı kapatır. |

`SqliteMessageHistory`; `path`, `wal` ve `busy_timeout` ekler. `limit=None`
sınırsız retention'dır; production için explicit limit ve queue capacity
tercih edilmelidir.

## Kararlılık kuralları

- Export edilen semboller ve belgelenmiş parametreler desteklenen public yüzeydir.
- `_` ile başlayan constructor parametreleri görülebilse de uygulama detayıdır.
- Snapshot dataclass'larına minor sürümlerde varsayılanlı alanlar eklenebilir.
- Yeni enum üyeleri ve opsiyonel parametreler geriye uyumlu biçimde eklenebilir.
- Cleanup, sıralama, timeout ve callback thread davranışları API sözleşmesidir.
