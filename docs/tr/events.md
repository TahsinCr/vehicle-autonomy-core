[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/events.md) | **Türkçe**

# Event'ler

Event paketi eş özellikli sync ve asyncio-native API sunar. Çağıran yapıya uygun
bus seçilir; callback modu kayıt sırasında doğrulanır.

## `EventBus`

```text
EventBus(*, history=None, error_policy=ErrorPolicy.ISOLATE, executor=None,
         replay_buffer_limit=1000, max_schedules=64, shutdown_timeout=5.0,
         actions=None, on_before=None, on_after=None,
         on_error=None, on_timeout=None)
```

- `history`: `None`, integer kapasite veya `EventHistory`.
- `executor`: subscriber çalıştırmak için opsiyonel executor.
- `replay_buffer_limit`: replay arkasında subscriber başına bekleyen live event.
- `max_schedules`: aktif `publish_every()` sınırı.
- `shutdown_timeout`: `close()` schedule thread'lerini toplam bekleme süresi.
- `actions` veya ayrı `on_*` hook'ları; iki biçim birlikte kullanılamaz.

Metotlar:

- `subscribe(callback, event_filter=None, event_type=None, predicate=None,
  once=False, times=None, replay=0) -> Subscription`
- `once(callback, ..., replay=0) -> Subscription`
- `publish(event) -> PublishResult`
- `wait_for(..., timeout=None) -> event | None`
- `query(..., limit=None) -> tuple[event, ...]`
- `latest(...) -> event | None`
- `publish_every(event, interval, times=None, immediately=True) -> Subscription`
- `clear()`, `close()`

Executor yoksa callback publish eden thread'de çalışır. Yavaş callback üreticiyi
yavaşlatabilir. Periyodik callback kapanmazsa `close()`,
`EventShutdownTimeoutError` yükseltir; thread zorla öldürülmez. Canlı schedule
sahiplikte kalır; callback çıktıktan sonra `close()` yeniden çağrılarak join
tamamlanır.

## `AsyncEventBus`

Async bus'ta `executor` yerine `delivery_mode=DeliveryMode.SEQUENTIAL` vardır.
Callback ve hook'lar coroutine olmalıdır. `publish`, `wait_for`,
`publish_every`, subscription cancellation ve `close` await edilir.
Başka thread'den `publish_threadsafe(event)` çağrılabilir.

```python
from src.core.events import AsyncEventBus, DeliveryMode

async def run() -> None:
    bus = AsyncEventBus[Telemetry](
        history=100,
        delivery_mode=DeliveryMode.CONCURRENT,
    )

    @bus.subscribe
    async def consume(event: Telemetry) -> None:
        ...

    await bus.publish(Telemetry(...))
    await bus.close()
```

`SEQUENTIAL` subscriber sırasını korur. `CONCURRENT`, eşleşen callback'leri
birlikte bekler ve hataları kararlı sonuçta toplar.

## Filter ve replay

`EventFilter(event_type=None, predicate=None)`, `isinstance` kontrolüyle sync
predicate'i birleştirir. Aynı parametreler bus metotlarına doğrudan verilebilir.

```python
events.subscribe(
    handle_warning,
    event_type=StatusEvent,
    predicate=lambda event: event.level >= 30,
    replay=10,
)
```

Replay atomik subscription sınırıdır. Pending buffer taşarsa yalnızca ilgili
subscription iptal edilir; hata `PublishResult` içinde döner, diğer subscriber'lar
event'i almaya devam eder.

## Sonuç, stats ve policy

- `PublishResult(matched, delivered, failed, errors)` ve `successful` property.
- `EventBusStats(published, delivered, failed)`; `bus.stats` üzerinden okunur.
- `subscriber_count`, aktif kayıt sayısıdır.
- `ErrorPolicy.ISOLATE` hatayı sonuçta döndürür; `RAISE` teslimat sonrası yükseltir.
- `DeliveryMode.SEQUENTIAL` ve `CONCURRENT` async teslimatı seçer.

## Callback policy'leri

```python
subscription = vehicle.subscribe(
    "ATTITUDE",
    handle_attitude,
    max_calls=100,
    frequency_hz=10.0,
    timeout=0.05,
    predicate=lambda event: event.message.roll is not None,
    enabled=True,
)

@subscription.on_error
def callback_failed(context):
    ...
```

`CallbackSubscription` parametreleri: `identifier`, `cancel`, `callback`,
`asynchronous`, `once`, `max_calls`, `frequency_hz`, `timeout`, `predicate`,
`enabled`, `on_before`, `on_success`, `on_error`, `on_timeout`, `on_after`.

Public üyeler: `enable`, `disable`, `enabled`, `active`, `cancel`, `invoke`,
`invoke_async` ve beş hook decorator'ı. Hook'lar
`CallbackContext(event, result=None, error=None, elapsed=0.0)` alır. Sync timeout
gözlemseldir; callback bittikten sonra raporlanır. Async timeout awaited callback'i
execution bütçesinde iptal eder.

## Named engine'ler

`EventEngine` isimlendirilmiş sync, `AsyncEventEngine` async kanal yönetir.
Constructor'ları history, error policy ve global hook ayarlarını alır. İkisi de
`add`, `remove`, `channel`, `channel_names`, `subscribe`, `once`, `publish`,
`publish_every`, `wait_for`, `start`, `stop`, `close` sunar.

```python
engine = EventEngine(history=50)
engine.start()
engine.subscribe("telemetry", consume)
engine.publish("telemetry", sample)
engine.stop()
```

## History, subscription ve hatalar

`EventHistory`: `append`, `latest`, `query`, `clear` abstract sözleşmesi.
`MemoryEventHistory(capacity=1000)` built-in bounded store'dur.
`Subscription` ve `AsyncSubscription`, `id`, `active`, idempotent `cancel` sunar.

Hatalar: `EventBusError`, `EventBusClosedError`, `InvalidEventHandlerError`,
`CallbackTimeoutError`, `EventShutdownTimeoutError`.

`EventBusActions`/`AsyncEventBusActions` global `on_before`, `on_after`,
`on_error`, `on_timeout` hook'larını gruplar. Hata hook'u
`EventErrorContext(event, error)`, timeout hook'u
`EventTimeoutContext(event_filter, timeout)` alır.
