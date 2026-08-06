[![Python 3.11+][python-shield]][python-url]
[![Repository license][license-shield]][license-url]

[English][readme-url] | **Türkçe**

# Vehicle Autonomy Core

Vehicle Autonomy Core, Kırlangıç Team'in araç projelerinde kullandığı ortak
Python çekirdeğidir. Bir hava, kara veya başka tür otonom araç projesinde tekrar
tekrar ihtiyaç duyulan altyapıyı bir araya getirir: dependency injection,
uygulama içi event'ler, mission yönetimi ve MAVLink haberleşmesi.

Bu depo tamamlanmış bir otonomi uygulaması değil, genel amaçlı bir araç
kutusudur. Aracın nereye gideceğine, hangi hedefi seçeceğine veya payload'un
nasıl davranacağına karar vermez. Bu kararlar core'u kullanan uygulamada kalır.

## Kapsam

Core şunları sağlar:

- küçük ve genel `Model` ile `Service` taban sınıfları;
- senkron ve asyncio tabanlı event bus'lar;
- ortak yaşam döngüsüne sahip isimlendirilmiş event kanalları;
- dependency kaydı, injection, scope ve deterministik kaynak temizliği;
- kuyruk, öncelik, retry ve zincir desteği olan araçtan bağımsız mission motoru;
- tek okuyuculu MAVLink bağlantısı ve router;
- asyncio köprüsü, uygulama paketleri, peer canlılığı ve request/response;
- sınırlı worker kullanan dispatcher ve taşımaya uygun remote-log modelleri.

Core bilinçli olarak şunları içermez:

- guidance, navigation, control veya rota planlama algoritmaları;
- ARM, takeoff, landing gibi araca özel komutlar;
- belirli bir ürünün ya da yarışmanın görev seçme kuralları;
- kamera, görüntü işleme, hedef takibi veya payload uygulamaları;
- UI, yer kontrol istasyonu, veritabanı veya loglama backend'i;
- uygulama paketleri için kimlik doğrulama, şifreleme veya teslim garantisi.

Pratik sınır şudur: aracın somut görevini bilen kod araç uygulamasında; tekrar
kullanılabilen koordinasyon ve taşıma mekanizmaları core'da yer alır.

## Mimari

```text
araç uygulaması
├── domain servisleri ve araç entegrasyonları
├── somut Mission sınıfları
└── UI / yapılandırma / kalıcı depolama
             │
             ▼
Vehicle Autonomy Core
├── abstracts       ortak model ve servis sözleşmeleri
├── dependency      nesne oluşturma ve sahiplik
├── events          uygulama içi haberleşme
├── mission         genel görev zamanlama
└── mavlink         taşıma ve uygulama mesajlaşması
             │
             ▼
Python standart kütüphanesi + opsiyonel pymavlink
```

Bağımlılıklar core'a doğru akar. Core bir araç projesini, UI framework'ünü veya
uygulamaya özel mission kodunu import etmez.

## Gereksinimler ve kurulum

- Python 3.11 veya daha yeni bir sürüm
- Yalnızca gerçek bir MAVLink bağlantısı açılacaksa `pymavlink`
- Abstract, event, dependency injection ve mission katmanlarında üçüncü taraf
  çalışma zamanı bağımlılığı yoktur

MAVLink olmadan yerel geliştirme kurulumu:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

MAVLink kullanılacaksa opsiyonel bağımlılığı da kurun:

```bash
python -m pip install -e '.[mavlink]'
```

Windows'ta sanal ortamı `.\.venv\Scripts\Activate.ps1` ile etkinleştirin.

### Depoyu `src/core` olarak kullanma

Önerilen kullanım, bu deponun tüketici projedeki `src/core` konumuna
yerleştirilmesidir. Git submodule bu yerleşim için uygundur:

```bash
git submodule add https://github.com/Kirlangic-Team/vehicle-autonomy-core.git src/core
```

```text
projeniz/
├── src/
│   ├── __init__.py
│   ├── core/                 # bu depo
│   │   ├── __init__.py
│   │   ├── dependency/
│   │   ├── events/
│   │   ├── mission/
│   │   └── mavlink/
│   └── uygulamaniz/
└── tests/
```

Tüketici importları değişmez:

```python
from src.core import DependencyContainer, EventBus, MissionEngine
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime
```

Paket içindeki importlar relative olduğu için aynı checkout kaynak kodu
değişmeden `vehicle_stack.core` gibi başka bir üst paket altında da açılabilir.

## Modül haritası

| Modül | Sorumluluk |
|---|---|
| `abstracts.py` | `Model` serialization ve `Service` yaşam döngüsü sözleşmesi |
| `dependency/container.py` | container, kayıt yardımcıları, scope, çözümleme ve shutdown |
| `dependency/registration.py` | token, `Inject`, `Lifetime` ve provider kayıtları |
| `dependency/injection.py` | constructor ve fonksiyon injection |
| `dependency/annotations.py` | type hint ve injection marker çözümleme |
| `dependency/resolution.py` | çözümleme context'i ve döngü tespiti |
| `dependency/lifecycle.py` | cache kaynaklarını izleme ve sync/async kapatma |
| `dependency/errors.py` | dependency hata sınıfları |
| `events/event_bus.py` | thread-safe senkron teslim |
| `events/async_event_bus.py` | asyncio tabanlı teslim |
| `events/engine.py` | isimlendirilmiş senkron ve asenkron event kanalları |
| `events/actions.py` | before, after, error ve timeout hook'ları |
| `events/filtering.py` | event tipi ve predicate filtreleri |
| `events/history.py` | sınırlı bellek geçmişi |
| `events/subscription.py` | iptal edilebilir abonelik nesneleri |
| `events/contracts.py` | teslim şekli, hata politikası, sonuç ve istatistikler |
| `events/errors.py` | event bus hata sınıfları |
| `mission/base.py` | uygulamaya ait mission'lar için taban sınıf |
| `mission/controller.py` | mission'a sunulan abstract kontrol sınırı |
| `mission/engine.py` | registry, durum, yaşam döngüsü ve public mission facade |
| `mission/lifecycle.py` | pause, resume, stop, progress, checkpoint ve tamamlama |
| `mission/scheduling.py` | kuyruk, çakışma, öncelik, retry ve zincirler |
| `mission/runtime.py` | motorun sahip olduğu durum ve bağlı mission controller |
| `mission/models.py` | snapshot, event, retry politikası ve zincir modelleri |
| `mission/enums.py` | faz, öncelik, politika ve geçiş kuralları |
| `mission/errors.py` | mission hata sınıfları |
| `mavlink/endpoint.py` | doğrulanan serial, UDP ve TCP ayarları |
| `mavlink/connection.py` | `pymavlink` taşıma sahipliği ve kilitli I/O |
| `mavlink/router.py` | tek receive döngüsü, route, wait, geçmiş ve istatistik |
| `mavlink/filter.py` | MAVLink metadata ve predicate filtreleri |
| `mavlink/message.py` | alınan mesaj envelope modeli |
| `mavlink/cache.py` | key başına sınırlı ve thread-safe mesaj geçmişi |
| `mavlink/channel.py` | router'dan asyncio'ya sınırlı kuyruk köprüsü |
| `mavlink/application.py` | JSON paketleri ve `V2_EXTENSION` parçalama |
| `mavlink/peer.py` | peer durumu, canlılık ve ilişkili request'ler |
| `mavlink/dispatch.py` | sınırlı application handler çalıştırma |
| `mavlink/remote_log.py` | doğrulanan remote-log kayıt ve batch modelleri |
| `mavlink/runtime.py` | üst seviye yaşam döngüsü ve mesajlaşma facade'ı |
| `mavlink/protocols.py` | uyumlu MAVLink mesajları için structural type'lar |

`annotations.py`, `resolution.py`, `lifecycle.py` ve `mission/runtime.py` gibi
dosyalar uygulama ayrıntılarıdır. Çoğu uygulama doğrudan bu dosyalar yerine
`src.core`, `src.core.dependency`, `src.core.events`, `src.core.mission` ve
`src.core.mavlink` public exportlarını kullanmalıdır.

## Temel sözleşmeler

### Model

`Model.to_dict()` modelin public durumunu döndürür. Adı `_` ile başlamayan
dataclass field'ları ile normal instance veya slot attribute'ları otomatik
olarak sonuca eklenir.

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

`to_dict()` değerleri görünür hâle getirir; genel amaçlı bir JSON encoder
değildir. Wire modelleri doğrulama veya güvenli kopya gerektiğinde kendi
serialization metotlarını sunar.

### Service

`Service` ortak yaşam döngüsü biçimidir. Somut servis `start()` ve `stop()`
metotlarını uygular, açtığı kaynakların sahipliğini kendisi üstlenir.

```python
from src.core import Service


class Worker(Service):
    def start(self) -> None:
        print("worker başladı")

    def stop(self) -> None:
        print("worker durdu")
```

## Dependency injection

`DependencyContainer` provider olarak sınıf, factory veya hazır instance
kullanabilir. Token bir sınıf ya da hash edilebilen başka bir değer olabilir.

### Yaşam süreleri

| Lifetime | Davranış |
|---|---|
| `transient` | her çözümlemede yeni değer üretir |
| `singleton` | kaydı yapan container'a ait tek değer üretir |
| `scoped` | her child scope için bir değer üretir |

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

Constructor annotation'ları autowire için kullanılır. Parametre adı veya
annotation yeterli değilse açık dependency map verilebilir:

```python
container.singleton("vehicle-id", instance="IKA-01")
vehicle = container.build(
    lambda identifier: {"vehicle": identifier},
    dependencies={"identifier": "vehicle-id"},
)
```

### Injection decorator'ları

Bir fonksiyon veya sınıftaki eksik parametreler container'dan alınabilir.
Kullanıcının açıkça verdiği argüman hiçbir zaman ezilmez.

```python
from typing import Annotated

from src.core import Inject


@container.inject
def timestamp(clock: Annotated[Clock, Inject()]) -> float:
    return clock.now()
```

`strict=True`, injection adayı olan her annotated parametre için açık bir kayıt
bulunmasını zorunlu tutar. Opsiyonel bağımlılık `Inject(optional=True)` ile
belirtilebilir.

### Scope ve async provider

```python
root = DependencyContainer()
root.scoped(dict, factory=dict)

with root.create_scope() as first_scope:
    first = first_scope.resolve(dict)
    assert first is first_scope.resolve(dict)

with root.create_scope() as second_scope:
    assert second_scope.resolve(dict) is not first
```

Async factory'ler async yaşam döngüsüyle kullanılır:

```python
async def open_client() -> object:
    return object()


container.singleton("client", factory=open_client)
client = await container.resolve_async("client")
await container.shutdown_async()
```

`warmup()` ve `warmup_async()` seçilen cache'li provider'ları öncelik sırasıyla
önceden oluşturur. `unregister()` senkron cache değerlerini kapatıp token'ı
siler; `aclose()` kullanan değerlerde `unregister_async()` çağrılmalıdır.
Shutdown bütün kaynakları oluşturulma sırasının tersinde kapatmayı dener ve
birden fazla hata varsa bunları birlikte yükseltir.

Uygulamaya ait composition root için `BaseDependencyContainer` sınıfından
miras alıp kayıtları `configure()` içinde tutabilirsiniz.

## Event sistemi

### Senkron bus

`EventBus` thread-safe çalışır. Executor verilmezse handler'lar `publish()`
çağrısını yapan thread üzerinde çalışır.

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

Abonelikler sınırlandırılabilir ve filtrelenebilir:

```python
positions.once(lambda event: print("ilk:", event))
positions.subscribe(
    lambda event: print("sonraki üç:", event),
    times=3,
    predicate=lambda event: event.latitude > 0,
    replay=1,
)
```

Aynı filtre birden fazla yerde kullanılacaksa `EventFilter` oluşturulabilir.
History açıksa `latest()` son eşleşmeyi, `query()` saklanan eşleşmeleri döndürür.
`wait_for()` bir eşleşme gelene kadar bekler ve timeout olursa `None` verir.

`publish_every(event, interval, times=...)` aynı event'i daemon bir schedule
üzerinde yayınlar ve iptal edilebilir bir `Subscription` döndürür.

### Hook'lar ve hata politikası

```python
from src.core import ErrorPolicy, EventBus


events = EventBus[str](
    error_policy=ErrorPolicy.ISOLATE,
    on_before=lambda event: print("önce", event),
    on_after=lambda event, result: print("sonra", result.delivered),
    on_error=lambda context: print("handler hatası", context.error),
    on_timeout=lambda context: print("bekleme timeout", context.timeout),
)
```

`ISOLATE`, handler hatalarını `PublishResult` içinde toplar. `RAISE` bunları
`ExceptionGroup` olarak yükseltir. Tekrar kullanılacak hook kümeleri
`EventBusActions` içinde tutulabilir. `stats`, toplam yayın, teslim ve hata
sayılarını verir.

Opsiyonel bir `Executor`, senkron callback'leri executor thread'lerinde
çalıştırır. `publish()` yine callback'lerin bitmesini bekler; `PublishResult`
hem iş gönderme hem handler hatalarını içerir.

### Asenkron bus

`AsyncEventBus` async handler kabul eder ve tek bir çalışan event loop'a aittir.
Teslim varsayılan olarak sıralıdır, istenirse eşzamanlı yapılabilir.

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

Async bus aynı filtre, replay, `once`, `times`, history, wait ve periyodik yayın
araçlarını sunar. Hook'larının da async olması gerekir. Bus çalışan event
loop'una bağlandıktan sonra başka bir thread'den `publish_threadsafe()`
kullanılabilir; sonuç `concurrent.futures.Future` olarak döner.

### İsimlendirilmiş kanallar

Bir uygulamadaki birden fazla kanal ortak ayar ve yaşam döngüsüyle yönetilecekse
`EventEngine` kullanılabilir:

```python
from src.core import EventEngine


with EventEngine(history=50) as events:
    events.subscribe("vehicle.position", print)
    events.once("vehicle.ready", lambda value: print("hazır:", value))

    events.publish("vehicle.position", {"lat": 39.925, "lon": 32.836})
    ready = events.wait_for("vehicle.ready", timeout=0.1)
```

Kanal adları küçük harfe çevrilir ve kanallar ihtiyaç olduğunda oluşturulur.
`channel()` belirli bus'ı döndürür, `add()` özel ayarlı bir bus ekler,
`remove()` tek kanalı kapatır. `stop()` bütün kanalları ve periyodik yayınları
kapatır. `AsyncEventEngine` aynı yapıyı await edilen işlemler ve
`AsyncEventBus` kanallarıyla sunar.

## Mission sistemi

Mission paketi araç davranışını koordinasyondan ayırır. Uygulama `Mission`
sınıflarını yazar; `MissionEngine` registry, thread, geçiş, kuyruk ve gözlenebilir
durumun sahipliğini alır.

### Mission tanımlama

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
        # Mission'ın açtığı donanım veya abonelikleri burada kapatın.
        pass


mission = SurveyMission()
named_mission = SurveyMission(name="B bölgesi taraması")

with MissionEngine() as engine:
    engine.launch(mission)
    snapshot = engine.wait(mission, timeout=5.0)
    assert snapshot is not None
```

Her instance pozitif ve benzersiz bir integer ID alır. Varsayılan isim sınıf
adından üretilir (`SurveyMission`, `Survey Mission` olur); çağıran taraf her
instance için adı değiştirebilir.

Mission ayarları sınıf üzerinde tanımlanır:

| Attribute | Anlamı |
|---|---|
| `priority` | küçük sayı daha yüksek yetki demektir |
| `resources` | mission'ın tek başına kullandığı kaynak adlarıdır |
| `blocks` | bu mission ile birlikte çalışamayacak mission sınıflarıdır |
| `tags` | grup işlemlerinde kullanılan etiketlerdir |
| `prerequisites` | daha önce başarıyla bitmesi gereken mission sınıflarıdır |
| `conflict_policy` | çakışmayı reddeder, kuyruğa alır veya düşük önceliği durdurur |
| `prerequisite_policy` | eksik ön koşulda reddeder veya kuyruğa alır |
| `tick_interval` | `tick()` çağrıları arasındaki beklemedir |
| `timeout_seconds` | maksimum çalışma süresi veya `None` değeridir |
| `queue_timeout_seconds` | maksimum kuyruk süresi veya `None` değeridir |
| `retry` | tekrar deneme sayısı ve gecikmesidir |

`start()` işi hazırlar, `tick()` ilerletir, `stop()` kaynakları kapatır. Somut
mission destekliyorsa `pause()` ve `resume()` override edilebilir. Mission
içinden motorla haberleşmek için `checkpoint()`, `update_progress()`,
`complete()`, `fail()` ve `wait_for_stop()` kullanılır.

### Zamanlama ve kontrol

`launch_many()` ve alias'ı `run_parallel()`, çakışmayan mission'ları aynı anda
başlatır. Çakışmalar ortak `resources` ve `blocks` üzerinden bulunur. `QUEUE`
politikası bekler; `PREEMPT_LOWER` yalnızca kesin olarak daha yüksek önceliğe
sahip mission'ın çakışan işi durdurmasına izin verir.

Motor komutları bir `Mission` nesnesi veya integer ID kabul eder:

```python
engine.pause(mission)
engine.resume(mission.id)
engine.stop_mission(mission, reason="operatör isteği")
engine.cancel(mission.id)
```

Çalışan mission kendisine bağlı `control` üzerinden işlem yapabilir; ancak daha
yüksek öncelikli bir mission'ı yönetemez. `stop_missions(tags=...,
resources=...)`, hedefleri doğrudan tanımadan yetkili olduğu aktif işleri seçip
durdurur.

`snapshot()`, `snapshots()` ve `manager_snapshot()` çağırana ait mapping'lerden
ayrılmış frozen çalışma kayıtları sağlar. `events` ve `transitions` normal
`EventBus` nesneleridir.
Geçmiş event'ler `MissionEventQuery` ile filtrelenebilir:

```python
from src.core.mission import MissionEventLevel, MissionEventQuery


important = engine.query_events(
    MissionEventQuery(minimum_level=MissionEventLevel.WARNING, limit=50)
)
```

### Mission zincirleri

Zincir, mission sınıflarını sırayla oluşturup çalıştırır:

```python
from src.core import MissionChain


chain = MissionChain(
    "survey-sequence",
    (SurveyMission, SurveyMission),
    stop_on_failure=True,
)
engine.start_chain(chain)
state = engine.chain_snapshot("survey-sequence")
```

Zincir girdileri instance değil sınıftır. Varsayılan durumda argümansız
oluşturulabilmeleri gerekir. Uygulama dependency destekli oluşturma istiyorsa
`MissionEngine` kurulurken `mission_factory=` verebilir.

Mission worker'ları ve scheduler daemon thread kullanır. `stop()` işbirliğine
dayalıdır: `start()` veya `tick()` içinde süresiz bloklanan bir mission motor
tarafından zorla güvenli hâle getirilemez. Worker `stop_timeout` içinde bitmezse
motor `MissionTimeoutError` yükseltir ve shutdown'ın tekrar denenebilmesi için
stopping durumunu görünür tutar.

## MAVLink

MAVLink paketi iki seviyede kullanılabilir. Normal giriş noktası
`MavlinkRuntime` sınıfıdır. Özel sahiplik gerektiğinde connection, router,
async channel, application channel, peer ve dispatcher ayrı ayrı da public'tir.

### Endpoint ve üst seviye runtime

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
    subscription = mavlink.on(
        ("HEARTBEAT", "GLOBAL_POSITION_INT"),
        lambda message: print(message.to_dict()),
    )
    position = mavlink.wait_for("GLOBAL_POSITION_INT", timeout=3.0)
    latest_heartbeat = mavlink.latest("HEARTBEAT")
    subscription.cancel()
```

TCP client için `MavlinkEndpoint.tcp(host, port)`, serial bağlantı için
`MavlinkEndpoint.serial(device, baud=...)` kullanılır. Şemasız `host:port`
değeri TCP client adresine dönüştürülür. Ağ portu, source ID, baud ve heartbeat
timeout bağlantı açılmadan doğrulanır.

`MavlinkRuntime.start()` önce client'ı, ardından application bileşenlerini
başlatır. `stop()` ters sırada kapatır ve bütün cleanup hatalarını korur.
`reconnect()` tam stop/start yapar. `state`, taşıma, application peer ve router
bilgisini birleştirir; yaşam döngüsü hataları `runtime.errors` üzerinden gelir.

### Filtre, geçmiş ve gönderim

```python
from src.core.mavlink import MavlinkMessageFilter


position_filter = MavlinkMessageFilter.for_types(
    "GLOBAL_POSITION_INT",
    source_systems={1},
    source_components={1},
    predicate=lambda message: message.relative_alt >= 0,
)

subscription = mavlink.on(position_filter, print)
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

Filtreler mesaj tipi, mesaj ID, source system, source component, native
`pymavlink` condition ve Python predicate'i birlikte kullanabilir. `once()` ilk
eşleşmeden sonra kendini iptal eder. Router `history()` metodu
`MavlinkMessageEnvelope` nesneleri, `latest()` ise ham mesajı döndürür.
`MavlinkClient` ayrıca `request_message_rate()`, `send()`, `call_mav()` ve
`call_raw()` sunar.

`send_named()` ve `call_mav()`, `connection.mav` üzerindeki düşük seviye
MAVLink metotlarını çağırır; parametreler seçilen dialect ile uyumlu olmalıdır.

### Tek okuyucu kuralı

```text
serial / UDP / TCP
        │
        ▼
MavlinkConnection       taşıma ve kilitli yazma işlemleri
        │
        ▼
MavlinkMessageRouter    tek recv_match() döngüsü
        │
        ├── filtreli aboneler
        ├── cache, geçmiş ve wait işlemleri
        ├── MavlinkAsyncChannel
        └── MavlinkApplicationChannel
```

Router başladıktan sonra aynı connection üzerinde başka bir bileşen
`recv_match()` çağırmamalıdır. Birden fazla okuyucu mesajları belirsiz biçimde
birbirinden çalar.

Router callback'leri receive thread üzerinde çalışır. Kısa tutulmalıdır. Yavaş
işler için uygulamaya ait kuyruk, `MavlinkAsyncChannel` veya
`MavlinkApplicationDispatcher` kullanılmalıdır. Stop sırasında receive thread
canlı kalırsa router `TimeoutError` yükseltir ve bağlantıyı çalışan thread'in
altından kapatmaz.

### Asyncio köprüsü

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

Özel loop verilmediyse channel kendi event loop'u içinden başlatılmalıdır.
Kuyruk dolduğunda en eski mesajı atar ve `dropped_messages` sayısını artırır.
`stop()` forwarding aboneliğini iptal edip kuyruğu temizler; yeniden başlatılan
channel önceki oturumdan eski mesaj teslim etmez.

### Uygulama paketleri

Aynı fiziksel bağlantı üzerinde uygulama mesajlaşmasını açmak için
`MavlinkRuntime` sınıfına `application_role` verilir:

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

Gönderici JSON nesnesini MAVLink `V2_EXTENSION` payload'larına böler ve CRC32
bütünlük kontrolü ekler. Assembler sırası karışmış fragment'ları kabul eder,
kaynakları system/component ve packet ID ile ayırır, çelişen tekrarları
reddeder ve tamamlanmayan paketleri süre sonunda temizler.

`MavlinkApplicationPacket` paket tipi, ID, timestamp, source ID ve JSON
uyumluluğunu doğrular. `to_dict()` bağımsız bir dictionary döndürür. Protokol
testleri veya çevrimdışı kullanım için `MavlinkApplicationCodec.encode()` ile
üretilen fragment'lar `MavlinkApplicationAssembler.accept()` metoduna
verilebilir.

`MavlinkApplicationPeer` heartbeat, ping/pong canlılığı ve response correlation
ekler. `MavlinkApplicationDispatcher`, peer paketlerine abone olup kayıtlı
handler'ları sınırlı bir thread pool'da çalıştırır. Handler
`MavlinkApplicationResult`, mapping veya `None` döndürebilir. Request'lere
otomatik `system.ack` ya da `system.error` gönderilir; notification cevap
beklemez.

Canlılık ve acknowledgement için kullanılan `system.*` paket tipleri core'a
ayrılmıştır. Uygulama paketleri `camera.capture`, `mission.status` veya
`logs.push` gibi namespace içeren isimler kullanmalıdır.

Bu protokol hatalı veya bozulmuş paketleri tespit eder. Şifreleme, kimlik
doğrulama veya teslim garantisi sağlamaz. Tüketici sistemin ihtiyaç duyduğu
güvenlik, yetki ve retry politikası ayrıca uygulanmalıdır.

### Remote log modelleri

Remote-log sınıfları yalnızca wire modelidir; log toplamaz veya saklamaz.

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

Kayıtlar metin, timestamp ve JSON uyumlu detail alanlarını doğrular. Batch
içindeki sequence değerleri kesin artan olmalı; kayıt sayısı, detail boyutu ve
encoded paket boyutu sınırlıdır. UI'ya özel severity isimleri bilinçli olarak
core'da yer almaz.

### Message cache ve structural type'lar

Router dışında key başına sınırlı bir geçmiş gerektiğinde `MessageCache`
kullanılabilir:

```python
from src.core.mavlink import MessageCache


cache = MessageCache(lambda item: item["type"], per_key_limit=10)
cache.add({"type": "position", "value": 1})
latest = cache.latest("position")
```

`MavlinkMessageEnvelope`, ham mesajın çevresinde router sequence, alınma zamanı,
mesaj tipi, ID ve source metadata'sını tutar. `MavlinkHeader` ve
`MavlinkMessage`, test ve adapter'lar için runtime-checkable structural
sözleşmelerdir; bunlardan miras almak gerekmez.

## Yaşam döngüsü ve concurrency notları

- Event handler'ları bus lock'larının dışında çağrılır.
- `EventBus` thread-safe'dir; `AsyncEventBus` tek event loop'a bağlıdır.
- MAVLink router subscriber'ları receive thread üzerinde çalışır.
- Dispatcher handler'ları sınırlı pending kapasitesi olan worker thread'lerde
  çalışır.
- Dispatcher stop yeni işi reddeder, başlamayan işi iptal eder, çalışan
  handler'ları bekler ve shutdown sonrasında geç response göndermez.
- Mission uygulamaları kendi worker thread'lerinde çalışır ve stop isteğiyle
  işbirliği yapmalıdır.
- Router, peer, mission ve runtime shutdown hataları görünür kalır; timeout
  başarılı kapanış gibi gösterilmez.
- Sürekli çalışan yollardaki queue ve history yapıları, sahibi kapasite sunduğu
  yerde sınırlıdır.
- Başarılı heartbeat bağlantının canlı olduğunu gösterir; aracın göreve hazır
  veya sensörlerin sağlıklı olduğunu kanıtlamaz.

## Test

Donanım gerektirmeyen bütün testleri depo kökünden çalıştırın:

```bash
python -m unittest discover -v
python -m compileall -q .
```

Geliştirme sırasında tek paket çalıştırılabilir:

```bash
python -m unittest discover -s tests/dependency -t . -v
python -m unittest discover -s tests/events -t . -v
python -m unittest discover -s tests/mission -t . -v
python -m unittest discover -s tests/mavlink -t . -v
```

Testler hem bağımsız checkout'u hem amaçlanan `src/core` yerleşimini kapsar.
MAVLink testleri fake nesneler kullanır ve flight controller istemez. Serial,
radyo, ağ ve hardware-in-the-loop davranışları tüketici araç projesinde ayrıca
test edilmelidir.

## Katkı

Yeni bir özellik eklemeden önce, ürün kavramlarını import etmeden birbirinden
bağımsız araç projelerinde kullanılıp kullanılamayacağını değerlendirin. Mümkün
olduğunda public importları koruyun, yaşam döngüsü ve hata yollarına test ekleyin
ve şu kuralları sürdürün:

- her fiziksel MAVLink bağlantısı için tek okuyucu;
- core içinde UI veya araca özel görev bağımlılığı olmaması;
- thread, loop ve I/O sahipliğinin açık olması;
- sürekli çalışan yollarda sınırlı queue ve history;
- taşıma kodu içinde gizli otonom karar bulunmaması.

Sürüm notları [CHANGELOG.md][changelog-url] dosyasında tutulur.

## Lisans

Copyright © 2026 TahsinCr.

Vehicle Autonomy Core yalnızca GNU General Public License v3.0
(`GPL-3.0-only`) ile lisanslanmıştır. Tam metin için [LICENSE][license-url],
telif bildirimi için [COPYRIGHT][copyright-url] dosyasına bakın.

<!-- Badges -->

[python-shield]: https://img.shields.io/badge/Python-3.11%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white
[license-shield]: https://img.shields.io/github/license/Kirlangic-Team/vehicle-autonomy-core.svg?style=for-the-badge

<!-- Links -->

[python-url]: https://www.python.org/downloads/
[readme-url]: https://github.com/Kirlangic-Team/vehicle-autonomy-core/blob/main/README.md
[changelog-url]: https://github.com/Kirlangic-Team/vehicle-autonomy-core/blob/main/CHANGELOG.md
[license-url]: https://github.com/Kirlangic-Team/vehicle-autonomy-core/blob/main/LICENSE
[copyright-url]: https://github.com/Kirlangic-Team/vehicle-autonomy-core/blob/main/COPYRIGHT
