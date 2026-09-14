[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/README.md) | **Türkçe**

# Vehicle Autonomy Core dokümantasyonu

Bu dokümantasyon Vehicle Autonomy Core v1.7 public API'sini açıklar. Kütüphane
araçtan bağımsızdır; UI veya araca özel görev mantığı eklemeden dependency
yönetimi, event'ler, mission orkestrasyonu ve MAVLink taşıması sunar.

## Dokümantasyon haritası

```text
Kurulum ve import
       │
       ▼
Core sözleşmeleri ──► Dependency injection ──► Event
                                             │
                                             ▼
                                          Mission
                                             │
                                             ▼
                              MAVLink ve uygulama protokolü
                                             │
                                             ▼
                                  Operasyon ve performans
```

- [Başlangıç](getting-started.md) — kurulum, kaynak yerleşimi ve ilk uygulamalar
- [Mimari](architecture.md) — modül sınırları, thread ve sahiplik
- [Core soyutlamaları](core.md) — `Model`, `Service` ve serialization
- [Dependency injection](dependency.md) — kayıt, çözümleme, scope ve cleanup
- [Event'ler](events.md) — sync/async bus, callback, hook, replay ve engine
- [Mission'lar](mission.md) — görev geliştirme, zamanlama ve orkestrasyon
- [MAVLink](mavlink.md) — bağlantı, routing, araçlar, history ve async runtime
- [Uygulama protokolü](application-protocol.md) — parçalı paket, peer ve dispatch
- [API indeksi](api-reference.md) — desteklenen tüm public semboller
- [Operasyon ve test](operations.md) — kapanış, gözlemlenebilirlik ve benchmark

## Okuma yolunu seçin

İlk kez kullanıyorsanız [Başlangıç](getting-started.md) sayfasını okuyun ve
ardından yalnızca ihtiyacınız olan modüle geçin. Her modül rehberi küçük ama
gerçekçi bir araç senaryosuyla başlar, ileri davranışları adım adım ekler.

| Yapmak istediğim… | Başlangıç sayfası |
|---|---|
| Servis oluşturmak ve yaşam sürelerini yönetmek | [Dependency injection](dependency.md) |
| Durum değişikliği yayınlamak veya bileşenleri ayırmak | [Event](events.md) |
| Araç işlerini çalıştırmak, duraklatmak veya zincirlemek | [Mission](mission.md) |
| Araç keşfetmek ve telemetri tüketmek | [MAVLink](mavlink.md) |
| Yapısal request/response paketleri taşımak | [Uygulama protokolü](application-protocol.md) |
| Bir imza, parametre veya hatayı hızla bulmak | [API referansı](api-reference.md) |
| Deployment limitleri ve sağlık kontrollerini hazırlamak | [Operasyon](operations.md) |

Her rehber tek başına okunabilir. Kavramlar lifecycle, concurrency ve hata
ayrıntılarından önce tanıtılır; baştan sona okumak en rahat yoldur, içindekiler
bağlantıları ise hızlı başvuru içindir.

## Import düzeni

Tüketici projeler bu depoyu çoğunlukla `src/core` konumunda kullanır:

```python
from src.core import DependencyContainer, EventBus, Mission, MissionEngine
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime
```

Paket kendi içinde relative import kullanır; bu nedenle farklı bir üst paket adı
altında da çalışır. `src.core.mavlink` API'leri opsiyonel taşıma bağımlılığını
root yüzeyine taşımamak için kökten export edilmez.

## Uyumluluk

- Python 3.10 ve üzeri
- MAVLink taşıması kullanılana kadar `pymavlink` opsiyoneldir
- Python çağrı semantiği gerektirdiğinde sync ve async API'ler ayrıdır
- Frozen snapshot modelleri dışarıya ayrık veri verir

Doküman ile yayınlanmamış kaynak kod ayrışırsa kaynak kod esas alınır. Aksi
belirtilmedikçe bu doküman v1.7 içindir.
