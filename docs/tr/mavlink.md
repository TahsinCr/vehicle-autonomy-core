[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/mavlink.md) | **Türkçe**

# MAVLink

MAVLink paketi dört seviyelidir: `MavlinkConnection` pymavlink bağlantısını,
`MavlinkMessageRouter` tek okuyuculu routing'i, `MavlinkClient` bu ikisinin ortak
API'sini, `MavlinkRuntime` callback/araç/history/application katmanını yönetir.
Çoğu uygulama runtime ile başlamalıdır.

## Endpoint

```text
MavlinkEndpoint(uri="udp:127.0.0.1:14550", baud=115200,
                source_system=255, source_component=0,
                dialect="ardupilotmega", autoreconnect=True,
                heartbeat_timeout=10.0)
```

```python
MavlinkEndpoint.udp("0.0.0.0", 14550, source_system=245)
MavlinkEndpoint.tcp("127.0.0.1", 5760)
MavlinkEndpoint.serial("/dev/ttyACM0", baud=921600)
```

`normalize_uri(uri)` adresi doğrular; `connection_kwargs()` pymavlink ayarlarını
döndürür. Port ve source ID değerleri bool veya aralık dışı integer kabul etmez.

## Connection

`MavlinkConnection(endpoint, connection_factory=None, mavutil_module=None)`.
Public API: `connect/start`, `stop/close`, `reconnect`, `receive(message_types=None,
condition=None, blocking=False, timeout=None)`, `send(message)`,
`send_named(name, **parameters)`, `request_message_rate(message_id, frequency_hz,
target_system=None, target_component=None)`, `call_mav`, `call_raw`,
`evaluate_condition`, `evaluate_condition_for_state`. `sent_messages` başarılı
gönderim sayısıdır. pymavlink yoksa gerektiği anda `MavlinkUnavailableError` gelir.

## Router

```text
MavlinkMessageRouter(connection, history_limit=512, cache_per_type=64,
                     poll_timeout=0.25, error_backoff=0.1,
                     stop_timeout=2.0, state_capacity=None,
                     source_capacity=None)
```

Connection başına tek receive thread'i açar. `state_capacity` latest
source/component/type, `source_capacity` condition state kaynak sayısını LRU ile
sınırlar. Varsayılan `None` uyumlu sınırsız davranıştır.

API: `start`, `stop/close`, `subscribe(callback, filter=None)`, `latest(filter=None)`,
`history(filter=None, limit=None)`, `wait_for(types, predicate=None, timeout=3.0,
after_sequence=None)`, `add_filter(predicate)`.

```python
@router.add_filter
def keep_known_network(envelope):
    return envelope.source_system in allowed_systems
```

Ingress filter receive thread'inde kayıt sırasıyla çalışır. False dönen mesaj
history, cache, discovery ve subscriber'a ulaşmaz; filter hızlı olmalıdır.

`MavlinkRouterStats`: `running`, `sequence`, `received_messages`,
`receive_errors`, `dispatch_errors`, `estimated_dropped_messages`,
`delivery_quality`, `started_monotonic`, `last_message_monotonic`,
`filtered_messages`, `state_evictions`, `cached_state_keys`.
`MavlinkRouterError(phase, error, envelope)` structured hata event'idir.

## Filter ve envelope

`MavlinkMessageFilter(message_types=None, source_systems=None,
source_components=None, message_ids=None, condition=None, predicate=None)`.
`for_types(*message_types, **criteria)` factory'si ve `matches()` metodu vardır.
Native `condition=` yalnızca live `subscribe()` için nedensel olarak doğrudur;
historical `latest/history/wait_for` bunu reddeder, `predicate` kullanılmalıdır.

`MavlinkMessageEnvelope` alanları: `sequence`, `message`, `message_type`,
`source_system`, `source_component`, `message_id`, `received_monotonic`,
`received_at`. `wrap()` metadata yakalar; `to_dict(include_payload=False)` ayrık
veri verir.

`MavlinkMessage` protocol'ü `get_header`, `get_type`, `get_msgId`,
`get_srcSystem`, `get_srcComponent`, `get_seq`, `get_msgbuf`, `to_dict`, `to_json`;
`MavlinkHeader` source/sequence metadata sözleşmesini tarif eder.

## Client

`MavlinkClient(endpoint=None, connection=None, router=None, router_options=None)`;
router ve connection lifecycle/send/receive API'sini birleştirir.
`configure_endpoint(endpoint)` yalnızca durmuşken kullanılabilir. Custom router
ile `router_options` birlikte verilmez.

## Sync runtime

```text
MavlinkRuntime(endpoint=None, *, client=None, router_options=None,
               application_role=None, channel=None, peer=None, dispatcher=None,
               workers=1, max_pending=64, channel_options=None,
               peer_options=None, heartbeat_timeout=5.0, vehicle_history=128,
               vehicle_state_retention=None, callback_capacity=1024,
               callback_action_capacity=1024)
```

`_delivery` internal'dır. Public yüzey:

- lifecycle/state: `start`, `stop`, `close`, `reconnect`, `running`, `state`;
- mesaj: `subscribe`, `once`, `wait_for`, `latest`, `send`, `send_named`;
- aksiyon: `on`, `on_start`, `on_stop`, `on_connected`, `on_disconnected`, `on_error`;
- storage/filter: `add_history`, `add_filter`, `prune_vehicles`;
- app protocol: `handle`, `notify`, `request`, `application_enabled`;
- izleme: `delivery_error`, `dropped_callbacks`, `errors`, `router`.

`subscribe` seçenekleri `max_calls`, `frequency_hz`, `timeout`, `predicate`,
`enabled` ve callback hook'larıdır.

```python
with MavlinkRuntime(endpoint) as link:
    @link.subscribe("ATTITUDE", frequency_hz=20.0)
    def attitude(message):
        ...

    @link.on_error
    def runtime_error(action):
        ...
```

`MavlinkRuntimeState(running, connected, application_enabled, peer_alive,
router)` ve `MavlinkRuntimeError(source, error)` gözlemlenebilir state'tir.
Lifecycle callback'leri `MavlinkAction(source, vehicle=None, component=None,
error=None)` alır.

## Async runtime

`AsyncMavlinkRuntime(endpoint=None, delivery_capacity=1024, action_capacity=1024,
callback_concurrency=1, **runtime_options)` aynı mantıksal API'yi sunar. Lifecycle,
transport ve wait işlemleri await edilir; registration, `latest`, `add_filter`,
`add_history`, `prune_vehicles` anlıktır. Callback coroutine olmalıdır.

Concurrency 1 sıralamayı korur. Büyük değer bağımsız telemetri callback'lerini
sınırlı paralel çalıştırır; lifecycle aksiyonları sıralı kalır. Telemetri taşması
en eski callback'i düşürüp sayar, action taşması fatal delivery hatasıdır.

## Araç ve component

`runtime.vehicles`, `MavlinkCollection`/`AsyncMavlinkCollection` nesnesidir.
Autopilot heartbeat `MavlinkVehicle` oluşturur; diğer source component'ler araca
bağlanır.

Collection: `get(id)`, tüm araçlarda `get_component(component_id)`, iteration,
`len`, `wait_for(timeout=None)`, `remove(id)`, `subscribe`, `on`, `on_added`,
`on_removed`, `on_connected`, `on_disconnected`, `on_error`.

Vehicle: `get_component`, `get_components`, `wait_for_component`,
`remove_component`, `on_component_added/removed/connected/disconnected`,
`latest`, `history`, `wait_for`, `subscribe`, `send`, `send_named`,
`request_message_rate`, `notify`, `request`, `handle`. Component, nested yönetim
dışında aynı targeted işlevleri sunar. Async tiplerde taşıma ve wait await edilir.

`MavlinkVehicleState(connected, last_seen_monotonic,
last_observed_monotonic)` endpoint state'idir. Connection durumunu heartbeat,
retention süresini ise kabul edilen her mesajın observed zamanı belirler.
`vehicle_state_retention` disconnected state'i süre sonunda kaldırır;
`prune_vehicles(older_than=...)` elle temizlik yapar. Connected state silinemez.

## Cache ve history

`MessageCache(key, per_key_limit=64, max_keys=None)`: `add`, `latest`, `all`,
`snapshot`, `clear`; `keys`, `len`, `stats`. `MessageCacheStats(keys, messages,
evicted_keys)`.

`MessageHistory(limit=1000, background=False, queue_capacity=1024,
batch_size=64, flush_interval=0.02)`: `append`, `query`, `latest`, `flush`,
`clear`, `close`. Query parametreleri `system_id`, `component_id`, `message_type`,
inclusive Unix `since/until`, tail `limit`.

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

WAL opsiyoneldir. NaN/Infinity JSON `null` saklanır, canlı mesaj değişmez.
`MessageRecord` sequence, source ID, type, receive zamanı ve payload taşır.
`HistoryWriterStats(submitted, processed, persisted, failed_records, queued,
batches, failed)`,
`writer_stats` üzerinden; gerçek hata `recording_error` üzerinden okunur.
Kalıcı bir history hatası runtime tarafından bir kez bildirilir ve ilgili
history canlı trafikten ayrılır. Storage'ın sahibi yine kullanıcıdır.

## Raw async channel

`MavlinkAsyncChannel(router, message_filter=None, maxsize=128, loop=None)`;
`start`, async `receive(timeout=None)`, `receive_nowait`, `pending_messages`,
`stop/close`. Restart yeni queue açar; eski session mesajları taşınmaz.
