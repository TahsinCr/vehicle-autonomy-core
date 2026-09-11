[![Python 3.10+][python-shield]][python-url]
[![Repository license][license-shield]][license-url]

[English][readme-url] | **Türkçe**

# Vehicle Autonomy Core

Vehicle Autonomy Core, otonom araç projeleri için yeniden kullanılabilir bir
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

- Python 3.10 veya daha yeni bir sürüm
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
git submodule add https://github.com/TahsinCr/vehicle-autonomy-core.git src/core
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
| `mission/engine.py` | registry, ortak durum ve public mission facade |
| `mission/lifecycle.py` | kullanıma hazır pause, resume, stop, progress ve tamamlama bileşeni |
| `mission/scheduler.py` | kullanıma hazır kuyruk, çakışma, öncelik ve retry bileşeni |
| `mission/orchestration.py` | execution bileşenleri arasındaki internal koordinasyon |
| `mission/chain.py` | sıralı zincir, context aktarımı ve karma aşama ilerletme |
| `mission/parallel.py` | kontrollü paralel gruplar ve birleşik sonuçlar |
| `mission/background.py` | owner'a bağlı background mission politikaları |
| `mission/execution.py` | immutable zincir, node, grup ve sahiplik modelleri |
| `mission/runtime.py` | motorun sahip olduğu durum ve bağlı mission controller |
| `mission/models.py` | lifecycle snapshot, event, sorgu ve retry politikası |
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
| `mavlink/async_runtime.py` | ortak taşıma üzerinde async yaşam döngüsü |
| `mavlink/vehicles.py` | keşfedilen araçlar, component'ler ve kaynak bazlı yönlendirme |
| `mavlink/actions.py` | decorator aksiyonları ve sınırlı async callback teslimi |
| `mavlink/handlers.py` | kaynağa özel application handler'ları ve async görev sahipliği |
| `mavlink/protocols.py` | uyumlu MAVLink mesajları için structural type'lar |

`dependency/annotations.py`, `dependency/resolution.py`,
`dependency/lifecycle.py`, `mission/orchestration.py`, `mission/chain.py`,
`mission/parallel.py`, `mission/background.py` ve `mission/runtime.py` uygulama
ayrıntılarıdır. Çoğu uygulama doğrudan bu dosyalar yerine `src.core`,
`src.core.dependency`,
`src.core.events`, `src.core.mission` ve `src.core.mavlink` public exportlarını
kullanmalıdır.

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
birden fazla hata varsa bunları birlikte yükseltir. Eşzamanlı çözümlemeler aynı
scope içinde yine tek bir instance alır. Birden fazla token altında kayıtlı bir
nesne son sahibi kaldırılana kadar açık kalır. Senkron shutdown async-only bir
cleanup ile karşılaşırsa sahipliği korur; işlem `shutdown_async()` ile yeniden
denenebilir. Kapanırken hata veren bir kaynak da container sahipliğinde kalır;
sonraki `shutdown()`/`shutdown_async()` yalnızca başarıyla kapanmayan kaynakları
yeniden dener. Dependency döngüleri hem thread'ler hem de bağımsız asyncio
task'ları arasında yakalanır. Eşzamanlı cleanup yolları kullanıcı kodunu
çağırmadan önce kaynağı sahiplenir; aynı instance iki kez kapatılmaz.

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
Replay kesin bir abonelik sınırıdır: replay sırasında gelen eşleşen canlı
event'ler geçmişin önüne geçmez, replay bittikten sonra teslim edilir.
Sıcak kod yollarında `query()` için `limit=` verilirse geriye doğru tarama,
yeterli sayıda güncel eşleşme bulunduğu anda durur.
Filtreli okumalar önce saklanan geçmişin snapshot'ını alır, ardından predicate'i
kilit dışında çalıştırır. Eşzamanlı yazmalar veya predicate'in yaptığı
değişiklikler bu snapshot'ı değiştirmez. `limit=` verilse de snapshot maliyeti
geçmiş boyutuyla orantılıdır; filtresiz sınırlı okumalar yalnızca istenen son
kayıtları kopyalar.

`publish_every(event, interval, times=...)` aynı event'i daemon bir schedule
üzerinde yayınlar ve iptal edilebilir bir `Subscription` döndürür. Bir bus
varsayılan olarak aynı anda en fazla 64 periyodik schedule kabul eder;
uygulamanın bilinçli olarak farklı bir sınıra ihtiyacı varsa `max_schedules=`
kullanılabilir. `replay_buffer_limit=`, yavaş bir replay arkasında biriken
canlı event'leri sınırlar. Taşma yalnızca ilgili subscriber'ı iptal eder ve
`PublishResult.errors` içinde bildirilir; diğer subscriber'lar eventi almaya
devam eder. `ErrorPolicy.RAISE` seçiliyse normal toplu hata yükseltilir.
`close()` dönmeden önce senkron periyodik schedule thread'lerini durdurup bekler.
`shutdown_timeout=` bu beklemeyi sınırlar; kullanıcı callback'i dönmezse
`EventShutdownTimeoutError` yükseltilir ve Python thread'i zorla sonlandırılmaz.

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
sınıflarını yazar; `MissionEngine` registry, thread ve gözlenebilir durumun
sahipliğini alır. Yaşam döngüsü ile zamanlama davranışı gizli mixin kalıtımı
yerine kullanıma hazır iki bileşen tarafından sağlanır.

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
| `timeout_seconds` | pause süreleri hariç maksimum aktif çalışma süresi veya `None` değeridir |
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

Uygulama genelinde backpressure gerektiğinde
`MissionEngine(max_active_missions=..., max_queued_missions=...)`
kullanılabilir. İki sınır da opsiyoneldir. Aktif kapasite dolduğunda normalde
başlatılabilecek iş öncelik sırasında bekler; kuyruk kapasitesi dolduğunda
yeni mission açık bir hatayla reddedilir.

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
`EventBus` nesneleridir. Geçmiş event'ler `MissionEventQuery` ile
filtrelenebilir:

```python
from src.core.mission import MissionEventLevel, MissionEventQuery


important = engine.query_events(
    MissionEventQuery(minimum_level=MissionEventLevel.WARNING, limit=50)
)
```

### Lifecycle ve scheduler bileşenleri

Normal kullanımda ek ayar gerekmez; `MissionEngine()` kendi `MissionLifecycle`
ve `MissionScheduler` nesnelerini otomatik oluşturur. Uygulama yalnızca belirli
bir davranışı genişletmek isterse aynı public sınıfları doğrudan kullanabilir:

```python
from src.core import MissionEngine, MissionLifecycle, MissionScheduler


class ObservedLifecycle(MissionLifecycle):
    def progress(self, mission, value, *, reason=""):
        print(f"mission ilerlemesi: {value:.0%}")
        return super().progress(mission, value, reason=reason)


lifecycle = ObservedLifecycle()
scheduler = MissionScheduler()
engine = MissionEngine(lifecycle=lifecycle, scheduler=scheduler)

assert engine.lifecycle is lifecycle
assert engine.scheduler is scheduler
```

Motor her bileşeni tek bir owner'a bağlar. `engine.launch()`, `engine.pause()` ve
`engine.wait()` gibi mevcut çağrılar ana facade olarak kalır ve işlemleri bu
bileşenlere devreder. Doğrudan bileşen erişimi gerektiğinde aynı işlemler
`engine.scheduler` ve `engine.lifecycle` üzerinden de kullanılabilir. Özel bir
bileşen yalnızca ihtiyaç duyduğu davranıştan miras alır; motor artık çoklu
kalıtım kullanmaz.

### Mission orkestrasyonu

Zincir, mission sınıflarını sırayla oluşturur. Her çalıştırmanın kendine ait
immutable context'i vardır. Böylece mission, ilk girdiyi ve önceki sonucu
constructor üzerinden orkestrasyon verisi almadan okuyabilir:

```python
from src.core import Mission, MissionChain


class ReadTarget(Mission):
    def start(self):
        target = self.runtime.chain_context.input["target"]
        self.complete({"target": target, "ready": True})

    def stop(self):
        pass


class UseTarget(Mission):
    def start(self):
        previous = self.runtime.chain_context.previous_result
        self.complete({"accepted": previous["ready"]})

    def stop(self):
        pass


chain = MissionChain("target-flow", (ReadTarget, UseTarget))
run = engine.start_chain(chain, input={"target": "zone-a"})
state = engine.chain_snapshot(run.execution_id)
```

`context.results`, tamamlanan sonuçları node adlarıyla saklar. Tekrarlanan
mission tiplerine kararlı bir sıra eki verilir; istenirse `MissionNode` ile ad
açıkça seçilebilir. `stop_on_failure=True` varsayılan davranış olarak kalır.
Değer `False` olduğunda sıradaki aşama `previous_mission.phase` bilgisini de
alarak terminal sonucu bilinçli biçimde ele alabilir.

Kontrollü paralel grup, mevcut bağımsız `run_parallel()` yardımcısına toplu
durum ve hata politikası ekler:

```python
from src.core import (
    MissionNode,
    MissionParallelGroup,
    ParallelFailurePolicy,
)


group = MissionParallelGroup(
    "checks",
    (
        MissionNode("health", HealthCheck),
        MissionNode("position", PositionCheck),
    ),
    ParallelFailurePolicy.CANCEL_REMAINING,
)
run = engine.start_parallel(group)
state = engine.wait_parallel(run.execution_id, timeout=5.0)
engine.cancel_parallel(run.execution_id)  # aktif child'lara yayılır
```

`WAIT_ALL` bütün child'ların terminal duruma gelmesini bekler.
`CANCEL_REMAINING` hata sonrasında aktif kardeşleri iptal eder;
`STOP_REMAINING` ise durdurur. Ortak resource ve `blocks` çakışmaları grup
başlamadan kontrol edilir. Sonuçlar immutable `state.result` mapping'inde
toplanır.

Paralel grup zincirde tek bir aşama olarak da kullanılabilir. İki child
`Prepare` sonucunu alır; `Finish` ise `left` ve `right` birleşik sonucunu okur:

```python
from src.core import MissionParallelStage


parallel = MissionParallelStage(
    "work",
    (MissionNode("left", LeftWork), MissionNode("right", RightWork)),
    ParallelFailurePolicy.STOP_REMAINING,
)
chain = MissionChain("mixed-flow", (Prepare, parallel, Finish))
engine.start_chain(chain)
```

Uzun süre çalışan destek işi normal bir mission olarak kalır ve bir mission'a,
zincir çalıştırmasına veya paralel çalıştırmaya bağlanabilir:

```python
from src.core import BackgroundFailurePolicy, OwnerTerminationPolicy


foreground = ForegroundMission()
engine.launch(foreground)
engine.launch_background(
    StatusPublisher(),
    owner=foreground,
    termination_policy=OwnerTerminationPolicy.STOP_WITH_OWNER,
    failure_policy=BackgroundFailurePolicy.FAIL_OWNER,
)
```

Güvenli varsayılan, owner bittiğinde background mission'ı durdurur.
`CANCEL_WITH_OWNER` iptal semantiğini korur; `KEEP_RUNNING` ise açıkça
seçilmelidir. `stop_chain()`, `cancel_chain()`, `stop_parallel()` ve
`cancel_parallel()` işlemleri normal mission lifecycle çağrılarıyla child'lara
yayılır; ek bir worker thread mekanizması kullanılmaz.

`wait_chain()` ve `wait_parallel()` polling yapmadan terminal sonucu bekler.
Tamamlanan zincir ve paralel snapshot'lar `execution_history` kadar saklanır;
varsayılan değer 256'dır. Uygulama bir sonucu daha erken bırakmak isterse
`forget_chain()` ve `forget_parallel()` kullanabilir. Unutulan orkestrasyon
çalışması için oluşturulan mission instance'ları terminal durumdaysa engine
registry'sinden de bırakılır.

Zincir ve grup girdileri instance değil sınıftır. Varsayılan durumda argümansız
oluşturulabilmeleri gerekir. Uygulama dependency destekli oluşturma istiyorsa
`MissionEngine` kurulurken `mission_factory=` verebilir.

Mission worker'ları ve scheduler daemon thread kullanır. `stop()` işbirliğine
dayalıdır: `start()` veya `tick()` içinde süresiz bloklanan bir mission motor
tarafından zorla güvenli hâle getirilemez. Worker `stop_timeout` içinde bitmezse
motor `MissionTimeoutError` yükseltir ve shutdown'ın tekrar denenebilmesi için
stopping durumunu görünür tutar. Motor aynı mission nesnesi üzerinde `start()`,
`tick()`, `pause()`, `resume()` veya `stop()` callback'lerini eşzamanlı çağırmaz.
Transition aboneleri engine state lock'u dışında çalışır ve başka bir lifecycle
komutu verebilir.
`start()`/`tick()` içinden `complete()` veya `fail()` çağrılırsa callback hemen
sonlanır; terminal durum ve kaynak bırakma stack açıldıktan sonra yapılır.
`stop()` hata verirse mission `STOPPING` durumunda ve resource sahibi olarak
kalır; `MissionCleanupError` cleanup'ın tamamlanmadığını bildirir. Alttaki sorun
çözüldükten sonra lifecycle işlemi yeniden çağrılabilir. Cleanup başarılı
olmadan resource başka bir mission'a verilmez. Terminal mission'lar yeni
checkpoint kabul etmez ve checkpoint event adını aynı isimli value ezemez.
Paralel aşama sonucu grubu `node` ile tanımlar ve bitiş sırasına bağlı bir
child ID yerine `mission_id=None` taşır.

## MAVLink

MAVLink paketi iki seviyede kullanılabilir. Normal giriş noktası
`MavlinkRuntime` sınıfıdır. Özel sahiplik gerektiğinde connection, router,
async channel, application channel, peer ve dispatcher ayrı ayrı da public'tir.

Router, istenmeyen trafiği latest state, cache, history, araç keşfi ve
abonelere ulaşmadan reddedebilir. `add_filter()` istenen sayıda senkron envelope
predicate'i kabul eder ve iptal edilebilir bir `Subscription` döndürür. Hem
doğrudan hem decorator olarak kullanılabilir:

```python
@link.add_filter
def bilinen_sistemler(envelope):
    return envelope.source_system in {1, 2, 3}

mesaj_turleri = link.add_filter(
    lambda envelope: envelope.message_type in {
        "HEARTBEAT",
        "ATTITUDE",
        "GLOBAL_POSITION_INT",
    }
)

# Yalnızca mesaj türü filtresini kaldır.
mesaj_turleri.cancel()
```

Filtreler kayıt sırasıyla çalışır ve ilk ret sonucunda durur. Receive thread
üzerinde koştukları için hızlı ve bloklamayan işlemler olmalıdır. Bir filtre
hatası mesajı reddeder ve `filter` aşamalı router hatası olarak yayınlanır.

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
    subscription = mavlink.subscribe(
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

### Çoklu araç ve component yönetimi

Senkron callback için `MavlinkRuntime`, async callback için
`AsyncMavlinkRuntime` kullanılır. İkisi de bağlantı başına tek receive thread'i
kullanır. Araç keşfi autopilot heartbeat'i gerektirir; GCS veya yalnızca companion
olan sistemler araç kaydı oluşturmaz. Tanınan aracın component'leri gelen
mesajlardan keşfedilir. Aynı bağlantıdaki araçların system ID'leri farklı olmalıdır.

```python
link = MavlinkRuntime(
    endpoint,
    heartbeat_timeout=5.0,
    vehicle_history=128,
    vehicle_state_retention=60.0,
    router_options={"state_capacity": 2048, "source_capacity": 256},
)

@link.vehicles.on_added
def discovered(event):
    print("Araç keşfedildi:", event.vehicle.system_id)

@link.vehicles.subscribe("GLOBAL_POSITION_INT")
def position(event):
    print(event.source_system, event.source_component, event.message.lat)

with link:
    vehicle = link.vehicles.wait_for(timeout=5.0)
    if vehicle is not None:
        vehicle.request_message_rate("GLOBAL_POSITION_INT", frequency_hz=10)
        component = vehicle.get_component(1)
        if component is not None:
            subscription = component.subscribe("HEARTBEAT", print)
            subscription.cancel()
```

İlk keşfi yakalamak için callback'leri context'e girmeden kaydedin.
State temizliği opsiyoneldir: bağlantısı kesilmiş component ve araçlar verilen
süre sonunda kaldırılır. `link.prune_vehicles(older_than=...)` ile temizlik
elle de yapılabilir. Router sınırları LRU kullanır; filtreleme, eviction ve cache
sayaçları `link.state.router` ile `link.router.cache.stats` üzerinden okunur.
İsteğe bağlı kayıt için `MessageHistory` veya ondan türeyen
`SqliteMessageHistory` kullanılabilir. `latest()` artık geçmişten bağımsızdır;
her mesaj türünün son değerini tutar (router'da kaynak/tür başına). Bu değer
eski olabilir; bağlantı durumunu ve zaman damgasını ayrıca kontrol edin.

```python
from src.core.mavlink import MessageHistory, SqliteMessageHistory

with SqliteMessageHistory(
    "telemetry.sqlite3",
    limit=None,
    wal=True,
    busy_timeout=5.0,
) as history:
    with MavlinkRuntime(endpoint) as link:
        recording = link.add_history(history)
        # Uygulamanın mesaj alma/bekleme akışı burada çalışır.
        rows = history.query(system_id=12, component_id=1,
                             message_type="ATTITUDE", limit=20)
        last = history.latest(system_id=12, message_type="ATTITUDE")
        recording.cancel()
```

Bellekte kayıt için `MessageHistory(limit=1000)` kullanılır. Yüksek hızlı
akışlarda `MessageHistory(limit=1000, background=True)` JSON dönüşümünü sınırlı
bir writer thread'ine taşır; bu opsiyonel yol `queue_capacity`, `batch_size` ve
`flush_interval` ile ayarlanır. Küçük geçmişlerde varsayılan senkron kullanım
ek thread açmaz. İki sınıfta da
varsayılan sınır toplam 1000 kayıttır; `None` sınırsızdır. SQLite sınırı önceki
oturumlardaki kayıtları da kapsar. `query()` eskiden yeniye, bağımsız JSON
payload taşıyan `MessageRecord` nesneleri döndürür. Kaynak/tür filtrelerine
ek olarak `since`/`until` dahil Unix zaman sınırlarıdır. Sorgudaki `limit`, en
yeni eşleşen N kaydı seçer. `clear()` bütün kayıtları siler. Mesajlar JSON
uyumlu `to_dict()` sağlamalıdır. MAVLink'in sonlu olmayan float sentinel
değerleri (`NaN`, pozitif ve negatif sonsuzluk) JSON `null` olarak saklanır;
canlı mesaj nesnesi değiştirilmez.
`history.writer_stats` gönderilen, tamamlanan, kuyruktaki kayıt ve batch
sayılarını verir. WAL opsiyoneldir; çıkarılabilir depolama ve salt-okunur
senaryolar SQLite'ın varsayılan journal modunu koruyabilir.
Bellekte son N sorgusu yeterli eşleşmeyi bulunca durur; eşleşme yoksa tüm
geçmiş taranabilir. SQLite filtre ve limiti SQL içinde uygular. Kaynak ID'leri
0..255 arası tamsayı, zaman sınırları sonlu ve sıralı olmalıdır; mesaj türü
boş bırakılamaz.

`add_history` iki modda da senkrondur; çalışma sırasında eklenebilir ve yalnızca
sonraki trafiği kaydeder. Dönen abonelik iptal edilebilir. Runtime kapanırken
kayıt ayrılır; depolamayı kapatmak uygulamanın sorumluluğudur. Başka backend
için `MessageHistory` sınıfından türetilebilir. Kayıt hataları runtime'a
`history` kaynağıyla bildirilir. SQLite JSON dönüşümü ve toplu commit'ler
ayrı yazıcı thread'indedir. `queue_capacity=1024` bekleyen mesajları sınırlar;
`batch_size=64` ve `flush_interval=0.02` transaction gruplamasını ayarlar.
Taşmada yeni kayıt reddedilir
ve `recording_error` ayarlanır; disk hataları bu alandan ve `flush()`, sorgu,
`close()` çağrılarından görülür. Mesaj akışı bitse bile bu hatalar kontrol
edilmelidir. `flush(timeout=5.0)` önceden kabul edilmiş kayıtları bekler; sorgu
ve clear önce flush yapar, close yazıcıyı boşaltıp kapatır.
Sınırlı kuyruk sınırsız yükte kayıpsız kayıt garantisi vermez.
Sınırsız kullanımda bellek/disk izlenmelidir. Mevcut
`vehicle.history()` kısa tanılama tamponu olarak kalır; bu kayıttan bağımsızdır.

`vehicles.get(12)` var olan nesneyi döndürür, yoksa `None` verir; nesne üretmez.
`wait_for(timeout=...)` erişilebilir ilk aracı bekler, timeout veya runtime
kapanışında `None` döndürür; ID kabul etmez. `vehicle.get_component(id)` tek
component veya `None`, `vehicle.get_components()` tuple snapshot döndürür.
`vehicle.wait_for_component(timeout=...)` bağlı component bekler; async modda
await edilir. `remove_component(id)` bağlantısı kesilmiş component'i kaldırır.
`on_component_added`, `on_component_removed`, `on_component_connected` ve
`on_component_disconnected` doğrudan araç üzerindedir; callback veya decorator
olarak kullanılabilir. İterasyon snapshot kullanır:

```python
for vehicle in link.vehicles:
    vehicle.request_message_rate("ATTITUDE", frequency_hz=10)
```

`link.vehicles`, tek araç veya tek component üzerinden
abonelik açılabilir. Callback, ilgili kaynağın `MavlinkMessageEnvelope` nesnesini
alır. Koleksiyon abonelikleri sonradan keşfedilen kaynakları da kapsar.
Decorator ve doğrudan kayıt çağrılabilir `CallbackSubscription` döndürür. `cancel()`
her iki modda da senkrondur. `once=True` aboneliği teslim sırasında tüketir.
`latest(type)` ve `history(type=None)` kaynağa özel mesaj zarflarını döndürür;
`wait_for(type, timeout=...)` yeni mesaj bekler. Her araç ve component için
geçmiş ayrı tutulur ve `vehicle_history` ile sınırlanır.

```python
@vehicle.on_disconnected(once=True)
def disconnected(event):
    print(event.vehicle.system_id)

vehicle.on("error", lambda event: print(event.error))
```

Runtime: `on_start`, `on_stop`, `on_error`. Araç/component: `on_connected`,
`on_disconnected`, `on_error`. Araç koleksiyonu `on_added` ve `on_removed`
sunar; component keşif, kaldırma ve bağlantı callback'leri aracın
`on_component_*` metotlarıyla kaydedilir. Aksiyonlar `MavlinkAction` alır;
uygun olduğunda `source`, `vehicle`, `component`, `error` alanları doludur.
İsimli aksiyonlar ve genel `on()` hem callback hem decorator kabul eder.

Heartbeat kesilince nesne silinmez, disconnected olur. Yeniden heartbeat
geldiğinde aynı nesne ve abonelikler kullanılır. Araç canlılığı en az bir
component'ten heartbeat gelmesini ifade eder; araç üzerinden hedefli gönderim
ayrıca canlı ve keşfedilmiş autopilot gerektirir. `remove(id)` yalnızca bağlantısı
kesilmiş kayıtlarda çalışır ve aboneliklerini kapatır. Component üzerinden
gönderim o bileşeni; araç üzerinden gönderim keşfedilen autopilot'u hedefler.
`send_named()` target alanları olan mesajlar içindir; dışarıdan hedef ezilmesine
izin vermez. `notify()` ve `request()` yapılandırılmış application peer'i açık
hedef ve yanıt kaynak eşleştirmesiyle kullanır. Ortak peer durumu ve router cache'i
bağlantı seviyesindedir; araca özel durum yerine kullanılmamalıdır.

`send(message)`, hedef alanları olan mesajın kopyasını hedefleyip gönderir;
kullanıcının verdiği mesaj nesnesini değiştirmez.

```python
from src.core.mavlink import AsyncMavlinkRuntime

async def receive_positions(endpoint):
    link = AsyncMavlinkRuntime(endpoint, delivery_capacity=1024)

    @link.vehicles.subscribe("GLOBAL_POSITION_INT")
    async def position(event):
        print(event.source_system, event.message.lat)

    async with link:
        vehicle = await link.vehicles.wait_for(timeout=5.0)
        if vehicle is not None:
            await vehicle.request_message_rate("GLOBAL_POSITION_INT", 10)
            message = await vehicle.wait_for("GLOBAL_POSITION_INT", timeout=5.0)
            print(message)
```

Tüm keşfedilmiş araçlarda aynı component ID'sini aramak için
`link.vehicles.get_component(1)` kullanılır. Mevcut component nesnelerinin
tuple snapshot'ını döndürür; eşleşme yoksa sonuç `()` olur. Bağlantısı kesilmiş
component'ler de dahildir. Araç kimliği `component.system_id`, bağlantı durumu
`component.state.connected` üzerinden okunur. Bu sorgu iki modda da senkrondur:

```python
for component in link.vehicles.get_component(1):
    if component.state.connected:
        print(component.system_id, component.component_id)
```

`.aio` yoktur; keşfedilen nesneler runtime'ın modunu izler. Async modda get,
abonelik kaydı ve iptali senkron kalır; wait, gönderim, application request ve
yaşam döngüsü işlemleri await edilir. Bloklayan taşıma işlemleri loop'un ortak
executor'ünü kullanır. Async callback'ler tek tüketiciyle çalışır; thread'den
loop'a bildirimler birleştirilir. Varsayılan `callback_concurrency=1` callback
sırasını korur. Birbirinden bağımsız telemetri callback'leri için
`AsyncMavlinkRuntime(..., callback_concurrency=N)` ile sınırlı eşzamanlılık
açılabilir; bu modda da yaşam döngüsü aksiyonları sıralı kalır. İptal edilen bir taşıma coroutine'i, altta
başlamış iş bitene kadar onu sahipli tutar; gönderilmiş mesajı geri alamaz.
Telemetri ve yaşam döngüsü aksiyonlarının
sınırlı kuyrukları ayrıdır. Telemetri kuyruğu dolduğunda en eski callback
bırakılır; sayı `link.dropped_callbacks` ile okunur. Aksiyonlar öncelikli ve
sıralıdır: `on_added` içinde aynı keşif için `on_connected` veya component
keşif callback'i kaydedilebilir. `action_capacity` varsayılan olarak 1024'tür.
Bu kapasite de dolarsa `link.delivery_error` ayarlanır, `link.running` false
olur ve `on_error` üzerinden hata bildirilir. Kurtarma için stop/start gerekir;
yoğun keşif trafiğinde kapasite artırılabilir.
Hata durumunda runtime ve araç/component üzerinden yeni gönderim, request ve
wait çağrıları, asıl teslim hatasını neden olarak taşıyan `RuntimeError` verir.
Bekleyen araç/component wait'leri loop hata bildirimini işlediğinde uyanır.
Snapshot sorguları ve geçmiş okunabilir kalır. Başlamış bloklayan taşıma
işlemleri geri alınamaz; ham mesaj wait'i alttaki bekleme döndüğünde hatayı
görür. Doğrudan düşük seviyeli client/connection kullanımı runtime'ın hata
kontrolünü atlar.
Yavaş callback diğer callback'leri geciktirir fakat socket okuyucusunu bekletmez.
Mesaj ve keşif wait'leri callback kuyruğundan bağımsız uyanır.

Async taşıma çağrısının iptali gönderilmiş mesajı geri alamaz. Başlamış bir
bloklayan application request, timeout veya peer kapanışına kadar sürebilir.

Stop sırasında bekleyen callback'ler bırakılır ve restart'ta tekrar teslim
edilmez. Çalışan handler iptal edilir; iptale yanıt vermiyorsa kapanış açık
timeout hatası verir. Runtime start/stop hook'ları doğrudan await edilir.
Telemetri alıcıları mesaj geldiğinde sabitlenir; sonradan
eklenen abonelik kuyruktaki eski mesajı almaz. İptal edilenler teslimde atlanır.
Keşif hook'larının sonraki bağlantı hook'larını kurabilmesi için yaşam döngüsü
aksiyonları alıcılarını teslim anında belirlemeye devam eder.
Senkron start/stop işlemleri sıralanır; close açılış bitmeden kaynakları kapatmaz.
Sahip olunan thread'lerden çakışan yaşam döngüsü çağrıları, kendi kapanışlarını
bekleyerek kilitlenmek yerine açık hata verir.

Üst seviye senkron mesaj/keşif callback'leri, predicate ve hook'lar receive
thread'inde değil, ortak tek callback worker'ında çalışır. `callback_capacity`
(varsayılan 1024) bekleyen telemetri teslimlerini sınırlar; dolunca en eski
telemetri bırakılır ve `dropped_callbacks` artar. Aksiyonların ayrı FIFO sınırı
`callback_action_capacity=1024` olur; telemetri keşif bildirimlerini düşüremez.
Aksiyon taşması veya worker'ın beklenmedik çıkışı `delivery_error` üretir ve
`running` false olur; kurtarma için stop/start gerekir.
Yavaş callback diğer callback'leri geciktirir;
okuyucunun kuyruğa teslimi callback'in bitmesini beklemez. Stop bekleyenleri
bırakır. Çalışan senkron fonksiyon zorla kesilemez; dönmezse kapanış timeout
bildirir. Açık start/stop/remove hook'ları yaşam döngüsünü çağıran thread'dedir.
Düşük seviye router/EventBus abonelikleri ve senkron history yazımı bu worker
garantisine dahil değildir; yayını yapan thread'de çalışmaya devam eder.

Abonelikte `once`, `max_calls`, `frequency_hz`, `timeout`, `predicate` ve
`enabled` ayarlanabilir. `frequency_hz` üst sıklık sınırıdır, döngü başlatmaz;
aradaki olaylar atlanır. Devre dışı, filtrelenen veya sıklık sınırına takılan
olaylar çağrı sayısını tüketmez. `once` ve `max_calls` birlikte verilemez.

```python
@vehicle.subscribe("ATTITUDE", frequency_hz=10, timeout=0.5, max_calls=100)
def attitude(event):
    print(event.message)

@attitude.on_error
def failed(context):
    print(context.error)

attitude.on_success(lambda context: print("işlendi"))
attitude.disable()
attitude.enable()
```

`on_before`, `on_success`, `on_error`, `on_timeout`, `on_after` kayıt sırasında
parametre veya sonradan metot/decorator olarak eklenir. `CallbackContext`
içinde `event`, `result`, `error` ve saniye cinsinden `elapsed` bulunur.
Async kayıtta callback/hook'lar async olmalıdır. Senkron timeout fonksiyon
döndükten sonra ölçülür; async timeout iptal talep eder. Altyapı timeout'u
`CallbackTimeoutError` verir; kullanıcı kodunun attığı `TimeoutError` normal
error akışına girer. Hook'ların ayrı süre
sınırı yoktur. Bloklayan async kod ve iptali reddeden kod zorla durdurulamaz.
`on_after` kabul edilen çağrının temizliğinde çalışır; atlanan olaylarda hook
çalışmaz. Decorator sonucunu doğrudan çağırmak, ayarları uygulamadan orijinal
fonksiyonu çağırır.
Normal hook hataları aynı gruptaki sonraki hook'ları atlatmaz. Success ve
cleanup hataları yerel error hook'larına ulaşır; birden fazla hata exception
group içinde korunur. İptal sinyali yayılmaya devam eder.

Keşfedilen nesnelerin kimlik alanları salt okunurdur. Seçili autopilot component
silindiğinde veya timeout olduğunda bağlı diğer autopilot seçilir. Eşzamanlı
`close()` çağrıları aynı temizliğin tamamlanmasını bekler. Async çağıranın
iptali ortak kapanış işlemini iptal etmez.

Application handler'ları `@link.handle("command.name")`,
`@vehicle.handle("command.name")` veya `@component.handle("command.name")`
ile kaydedilir. Seçim önceliği component, araç, sonra runtime'dır. Callback
doğrudan verildiğinde iptal edilebilir abonelik döner; aynı kaydı değiştirmek
için `replace=True` gerekir. Araç başına worker havuzu açılmaz, sınırlı
application dispatcher paylaşılır. Senkron runtime'da normal fonksiyon,
async runtime'da `async def` kullanılır. Async application handler'ları runtime
loop'unda çalışır; kapanışta iptal edilir ve tamamlanmaları beklenir. Varsayılan
`workers=1` handler sırasını korur; yalnızca handler'lar birbirinden bağımsızsa
ve daha yüksek throughput gerekiyorsa sınırlı worker sayısı artırılmalıdır.

Async runtime'daki `send`, `send_named`, `notify`, `request` ve ham mesaj
`wait_for` çağrıları await edilir. `messages`, `packets` ve `errors` birer
`AsyncEventBus` nesnesidir: `await link.messages.subscribe(callback)` kullanılır.
Üst seviye `link.subscribe(...)` ve araç/component abonelik kayıtları ise
senkrondur; decorator ve `once=True` destekler.

`with` / `async with` ortak bağlantıyı ve sahip olunan servisleri kapatır;
araç nesneleri için ayrı bağlantı açmak/kapatmak gerekmez. Runtime başlangıcı
ilk heartbeat el sıkışmasını beklemeye devam eder; bu süre endpoint üzerindeki
`heartbeat_timeout` ile belirlenir.

Geçiş: `runtime.on(message_type, callback)` yerine
`runtime.subscribe(message_type, callback)` kullanın. `on()` artık yaşam döngüsü
aksiyonları içindir. Çoklu araçta varsayılan connection hedefi ve ortak cache
yerine araç/component kapsamındaki işlemleri kullanın.

### Filtre, geçmiş ve gönderim

```python
from src.core.mavlink import MavlinkMessageFilter


position_filter = MavlinkMessageFilter.for_types(
    "GLOBAL_POSITION_INT",
    source_systems={1},
    source_components={1},
    predicate=lambda message: message.relative_alt >= 0,
)

subscription = mavlink.subscribe(position_filter, print)
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
`pymavlink` condition ve Python predicate'i birlikte kullanabilir. Native
condition yalnızca canlı `subscribe()` tesliminde nedensel olarak doğrudur.
`latest()`, `history()` ve `wait_for()`, geçmiş state'i doğru biçimde yeniden
kuramayacağı için `condition=` içeren filtreleri reddeder; bu sorgularda
`predicate=` kullanılmalıdır. `once()` ilk
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

Router callback'leri receive thread üzerinde çalışır. Model inference, disk I/O,
network isteği veya başka bir bloklayıcı iş burada yapılmamalıdır. Bu işler için
uygulamaya ait kuyruk, `MavlinkAsyncChannel` veya
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
`maxsize`, thread-safe tek bekleme kuyruğunu sınırlar. Taşma olduğunda telemetri
güncel kalsın diye her zaman en eski bekleyen mesaj düşürülür; her düşürme
`dropped_messages` sayısını artırır. `stop()` forwarding'i iptal eder, kuyruğu
temizler ve bekleyen receiver'ları uyandırır. Bloklanmış `receive()` bu durumda
`RuntimeError` yükseltir; yeniden başlatılan channel önceki oturumdan mesaj
teslim etmez.

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
`max_inflight_assemblies`, `max_inflight_bytes` ve `max_completed_packets`,
tamamlanmamış trafiği ve yakın dönem duplicate takibini global olarak sınırlar.

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
python run_tests.py
```

Script `tests` altındaki bütün `test*.py` dosyalarını bulur ve herhangi bir test
başarısız olursa sıfırdan farklı exit code döndürür. Bunun doğrudan komut
karşılığı ve kaynak derleme kontrolü şöyledir:

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

Paket yerleşimi testleri hem `src.core` hem başka bir üst paket için geçici ve
gerçek paket ağaçları oluşturur. Amaçlanan submodule yerleşimi ve relative
importlar, testin içine gömülmüş özel bir yükleyici yerine temiz alt süreçlerde
normal importlarla doğrulanır. MAVLink testleri fake nesneler kullanır ve flight
controller istemez. Serial, radyo, ağ ve hardware-in-the-loop davranışları
tüketici araç projesinde ayrıca test edilmelidir.

Opsiyonel bağımlılık kuruluysa gerçek UDP loopback kontrolü şu komutla
çalıştırılabilir:

```bash
python -m unittest tests.mavlink.test_pymavlink_integration -v
```

GitHub Actions, donanımsız testleri Python 3.10 ile 3.14 arasında çalıştırır;
ayrıca wheel kurulumunu ve ayrı bir `pymavlink` işinde bu loopback testini
doğrular.

### Performans regresyon ölçümü

Depo kökündeki benchmark; donanım veya ağ bağlantısı açmadan model, senkron ve
asenkron event, dependency, MAVLink ve mission yollarını ölçer:

```bash
python run_benchmarks.py --quick
python run_benchmarks.py --json > benchmark.json
```

Sonuçlar genel yapılardan alana özel işlemlere doğru sıralanır. Beş zamanlı
çalışmanın medyanı; duvar zamanı, CPU zamanı, boş fonksiyon çağrısına
oran, işlem başına kalıcı bellek ve tek işlemin tepe bellek değeri verir.
Mutlak süreler sisteme göre değişir; regresyon karşılaştırmasını aynı donanım
ve Python sürümüyle yapmak gerekir.

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

[python-shield]: https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white
[license-shield]: https://img.shields.io/github/license/TahsinCr/vehicle-autonomy-core.svg?style=for-the-badge

<!-- Links -->

[python-url]: https://www.python.org/downloads/
[readme-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/README.md
[changelog-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/CHANGELOG.md
[license-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/LICENSE
[copyright-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/COPYRIGHT
