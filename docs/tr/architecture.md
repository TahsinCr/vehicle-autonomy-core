[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/architecture.md) | **Türkçe**

# Mimari

## Modül sınırları

| Modül | Sorumluluk | Sahip olmadığı konu |
|---|---|---|
| `abstracts` | Ortak model serialization ve service lifecycle | Uygulama politikası |
| `dependency` | Nesne oluşturma, scope ve disposal | Global iş durumu |
| `events` | Uygulama içi sync/async teslimat | MAVLink taşıması |
| `mission` | Mission state, yetki ve orkestrasyon | Araca özel aksiyonlar |
| `mavlink` | Taşıma, routing, araç görünümleri ve app paketleri | UI veya mission mantığı |

Uygulama bu katmanları composition root'ta birleştirir. Mission sınıfları
MAVLink runtime'ı dependency olarak alabilir; mission paketi araca özel davranış
import etmez.

## Sahiplik

- `DependencyContainer`, oluşturduğu veya instance olarak aldığı cache'li nesneyi sahiplenir.
- `EventBus`, kendi subscription ve periyodik schedule'larını sahiplenir.
- `MavlinkRuntime`, client, router, registry, callback delivery ve app bileşenlerini sahiplenir.
- `add_history()` ile bağlanan `MessageHistory` kullanıcıya aittir.
- `MissionEngine`, kayıtlı mission runtime state ve worker thread'lerini sahiplenir.

```python
with MessageHistory(background=True) as history:
    with MavlinkRuntime(endpoint) as link:
        link.add_history(history)
```

## Eşzamanlılık

`EventBus`, executor verilmezse callback'i publish eden thread'de çağırır.
`AsyncEventBus`, coroutine callback'leri sahibi olan loop'ta çalıştırır. Replay
sırasında gelen event'ler replay bittikten sonra teslim edilir.

Her MAVLink connection için tek router receive thread'i vardır. Ingress filter
ve kaynak/tür filtreleme bu sıcak yolda çalıştığı için hızlı olmalıdır. Callback
kuyrukları sınırlıdır. Async transport iptal edilse bile başlamış blocking işlem
sahipsiz bırakılmaz.

Mission scheduler launch kararlarını koordine eder. Worker `start()` ve periyodik
`tick()` çağrılarını yürütür. Callback tamamen sonlanmadan ve cleanup başarılı
olmadan resource bırakılmaz.

DI initialization gate'leri çift singleton/scoped üretimini önler. Döngüler
thread ve asyncio task'ları arasında algılanır. Disposal, registration lock'u
dışında ve kaynak başına tek sahiplikle çalışır.

## Hata yaklaşımı

- Hatalı ayar constructor aşamasında reddedilir.
- Subscriber hataları varsayılan olarak izole edilip `PublishResult` ile döner.
- Cleanup tüm kaynaklarda denenir ve hatalar korunur.
- Sınırlı kuyruk taşması sessizce gizlenmez.
- Timeout kullanıcı thread veya callback'ini zorla öldürmez.
- Snapshot ve stats nesneleri gözlemlenebilir durumu taşır.

## Genişletme noktaları

- Domain snapshot için `Model` türetin.
- Composition root için `BaseDependencyContainer` türetin.
- Farklı event storage için `EventHistory` uygulayın.
- Görev için `Mission`, farklı motor için gerekirse `MissionLifecycle` veya `MissionScheduler` türetin.
- Telemetri backend'i için `MessageHistory` türetin.
- Taşıma gerçekten farklıysa custom connection, router, peer veya dispatcher verin.
