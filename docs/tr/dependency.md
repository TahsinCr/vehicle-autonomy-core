[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/dependency.md) | **Türkçe**

# Dependency injection

Dependency paketi açık kayıt, constructor injection, sync/async resolution,
nested scope ve deterministik cleanup sağlar.

## Bu sayfada

- [Zihinsel model](#zihinsel-model)
- [Araç servisi örneği](#araç-servisi-örneği)
- [Lifetime'lar](#lifetimelar)
- [`DependencyContainer`](#dependencycontainer)
- [Injection](#injection)
- [Composition root](#composition-root)
- [Public hata ve alias'lar](#public-hata-ve-aliaslar)

## Zihinsel model

**Token** “ne istendi?”, **provider** “nasıl oluşturulur?”, **lifetime** ise
oluşan nesnenin sahibinin kim olduğu sorusunu cevaplar. `resolve()` constructor
annotation'larını takip ederek nesne grafiğinin tamamını kurar.

```text
VehicleStatusService
    ├── TelemetryStore   singleton: owner container başına bir tane
    └── OperationLog    scoped: child scope başına bir tane
```

Cache'lenen nesneler container'a aittir ve ters oluşturulma sırasıyla
temizlenir. Transient nesnenin sahibi caller'dır.

## Araç servisi örneği

```python
from dataclasses import dataclass
from src.core import DependencyContainer

@dataclass(frozen=True)
class VehicleSettings:
    stale_after: float = 3.0

class TelemetryStore:
    def __init__(self) -> None:
        self.latest: dict[str, object] = {}

    def close(self) -> None:
        self.latest.clear()

class VehicleStatusService:
    def __init__(self, store: TelemetryStore,
                 settings: VehicleSettings) -> None:
        self.store = store
        self.settings = settings

with DependencyContainer() as container:
    container.instance(VehicleSettings, VehicleSettings())
    container.singleton(TelemetryStore)
    container.transient(VehicleStatusService)

    first = container.resolve(VehicleStatusService)
    second = container.resolve(VehicleStatusService)
    assert first is not second
    assert first.store is second.store
```

Status servisi her istekte yeniden oluşur; iki instance container-owned store'u
paylaşır. Context bittiğinde store'un `close()` metodu çalışır.

## Lifetime'lar

| Lifetime | Davranış | Cleanup sahibi |
|---|---|---|
| `TRANSIENT` | Her resolution için yeni instance | Çağıran |
| `SINGLETON` | Provider sahibinde tek instance | Kaydı yapan container |
| `SCOPED` | Scope başına tek instance | Scope container |

Cache'li kaynakların `close()`/`aclose()` metotları algılanır. Cleanup ters
oluşturma sırasında ilerler, her kaynağı dener ve birden fazla hata için
`ExceptionGroup` yükseltir. Kapanamayan kaynak sahiplikte kalır. Eşzamanlı
cleanup aynı instance'ı iki kez kapatmaz.

Başarısız unregister token'ı cleanup-pending durumda tutar. Eski kaynak
başarıyla kapanmadan aynı token yeniden kaydedilemez; eşzamanlı unregister
çağrıları tek disposal girişimini paylaşır. Container genelindeki başarısız
cleanup `cleanup_pending` değerini ayarlar; kalan cleanup tamamlanana kadar
kayıt, resolution ve yeni scope oluşturma engellenir. Başarılı shutdown
terminaldir. Parent shutdown başladığında child scope da parent provider'larına
dönemez.
Auto-wire aynı token reservation kuralına uyar; önceki instance dispose edilirken
concrete class yeniden üretilemez. Event-loop thread'inde yapılan senkron çağrı
async disposal'ı bekleyip kilitlenmez; `AsyncDependencyError` verir ve eşdeğer
async API'nin kullanılmasını ister.
Kaynak cleanup kodu kendisini çağıran aynı token disposal veya container
shutdown işlemini tekrar bekleyemez. Bu re-entry, deadlock yerine hemen
`DependencyResolutionError` üretir; ilgisiz eşzamanlı çağrılar ilk cleanup
girişimini paylaşmaya devam eder. Process-default container oluşturma ve
değiştirme işlemleri thread'ler arasında senkronize edilir.

## `DependencyContainer`

```text
DependencyContainer(*, parent=None, auto_wire=True)
```

`parent` bulunamayan kayıtları sağlar. `auto_wire=True`, kayıtlı olmayan concrete
sınıfları annotation'lı constructor üzerinden oluşturabilir.

Kayıt API'si:

- `register(token=None, provider=MISSING, *, abstract=None, concrete=MISSING,
  factory=MISSING, instance=MISSING, lifetime=TRANSIENT, dependencies=None,
  priority=100)`
- `singleton(...)`, `scoped(...)`, `transient(...)`
- `instance(token=None, instance=MISSING, *, abstract=None, priority=100)`
- `provider(token=None, *, abstract=None, lifetime=TRANSIENT,
  dependencies=None, priority=100)` decorator'ı
- `unregister(token)` ve `unregister_async(token)`

`token`/`abstract` lookup anahtarını; `provider`/`concrete`/`factory`/`instance`
oluşturma kaynağını seçer. `dependencies`, callable parametre adını token'a
eşler. Küçük sayısal `priority` warmup sırasında önce gelir.

Token provider dönüş annotation'ından çıkarılıyorsa geçersiz veya
çözülemeyen forward reference, inference'ı sessizce kapatmak yerine kayıt
sırasında `DependencyResolutionError` üretir.

```python
container = DependencyContainer()
container.instance("settings", settings)
container.singleton(
    Database,
    factory=create_database,
    dependencies={"config": "settings"},
)

@container.provider(lifetime=Lifetime.SCOPED)
def repository(database: Database) -> Repository:
    return Repository(database)
```

Resolution ve yaşam döngüsü:

- `resolve(token)`, `resolve_async(token)`
- `build(factory, dependencies=None)`, `build_async(...)`
- `can_resolve(token)` mevcut lifecycle durumunda gerçekten çözüm mümkünse true döner
- `has(token)` local veya parent zincirinde görünür bir kayıt varsa true döner
- `registered_tokens()` yalnız local token'ları listeler
- `create_scope()`
- `warmup(tokens=None, lifetimes=(SINGLETON,))`, `warmup_async(...)`
- `shutdown()`, `shutdown_async()`
- `closed` property’si
- `cleanup_pending` property’si

`DependencyCleanupPendingError`, eski kaynağın cleanup'ı beklerken token'ın
yeniden kullanılmasını bildirir. Sync resolution coroutine provider ve
async-only cleanup için
`AsyncDependencyError` verir; gizli event loop oluşturmaz.

## Injection

`Inject(token=MISSING, optional=False)` default değer veya `Annotated` metadata
olarak kullanılabilir. `injection()` eksik argümanları seçili/current/default
container'dan çözer; kullanıcının açıkça verdiği argümanı değiştirmez.

```python
from typing import Annotated
from src.core.dependency import Inject, injection

@injection(strict=True)
def handler(
    repository: Repository,
    clock: Annotated[Clock, Inject()],
    audit: Audit | None = Inject("audit", optional=True),
) -> None:
    ...
```

İmza: `injection(target=None, *, container=None, dependencies=None,
strict=False, **named_dependencies)`. Aynı özellik `container.inject()` olarak
da vardır. `strict=True`, çözülemeyen annotation ve dependency'leri açıkça bildirir.

## Composition root

```python
class ApplicationDependencies(BaseDependencyContainer):
    def configure(self) -> None:
        self.singleton(Database)
        self.scoped(UnitOfWork)
```

Constructor parametreleri `container`, `parent`, `set_as_default`, `auto_wire`.
Sınıf registration, resolution, scope, injection, warmup ve shutdown işlemlerini
`container` özelliğine yönlendirir.

Ambient yardımcılar: `get_current_container()`, `get_default_container()` ve
`set_default_container(container)`. Context exit, shutdown hata verse bile
current container ContextVar'ını sıfırlar.

## Public hata ve alias'lar

`DependencyError`, `DependencyNotFoundError`, `DependencyResolutionError`,
`DependencyCleanupPendingError`, `DependencyContainerClosedError`,
`CircularDependencyError`, `AsyncDependencyError`; `Token`, `DependencyMap` ve
`DEFAULT_PRIORITY=100`.
