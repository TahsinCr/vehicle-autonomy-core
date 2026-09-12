[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/README.md) | **Türkçe**

# Vehicle Autonomy Core dokümantasyonu

Bu dokümantasyon Vehicle Autonomy Core v1.7 public API'sini açıklar. Kütüphane
araçtan bağımsızdır; UI veya araca özel görev mantığı eklemeden dependency
yönetimi, event'ler, mission orkestrasyonu ve MAVLink taşıması sunar.

## Dokümantasyon haritası

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
