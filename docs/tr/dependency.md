[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/dependency.md) | **Türkçe**

# Dependency injection

Dependency paketi açık kayıt, constructor injection, sync/async resolution,
nested scope ve deterministik cleanup sağlar.

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
