[![Python 3.10+][python-shield]][python-url]
[![Repository license][license-shield]][license-url]

[English][readme-url] | **Türkçe**

# Vehicle Autonomy Core

Vehicle Autonomy Core, otonom araç projeleri için yeniden kullanılabilir bir
Python temelidir. Araca özel davranışları core'a taşımadan dependency injection,
senkron ve asenkron event, mission orchestration ve MAVLink haberleşmesi sunar.

Bu depo tamamlanmış bir otonomi uygulaması değil, genel amaçlı bir araç
kutusudur. Guidance, navigation, payload mantığı, görüntü işleme, UI ve ürüne
özel mission kararları core'u kullanan uygulamada kalır.

## Neler var?

- Hafif `Model` ve `Service` sözleşmeleri
- Scope ve deterministik senkron/asenkron cleanup destekli dependency injection
- Thread-safe ve asyncio-native event bus'lar
- Mission zamanlama, resource, öncelik, retry, chain, parallel group ve background
  mission desteği
- Araç ve component keşfi yapan tek okuyuculu MAVLink router
- Bounded callback teslimatı kullanan senkron ve asenkron runtime'lar
- Opsiyonel message history, application packet, request/response ve remote-log
  modelleri

## Gereksinimler ve kurulum

Python 3.10 veya daha yeni bir sürüm gerekir. `pymavlink` opsiyoneldir ve yalnızca
gerçek bir MAVLink bağlantısı açılırken kullanılır.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

```bash
python -m pip install -e '.[mavlink]'
```

## Repo yerleşimi

Önerilen kullanım, bu deponun tüketici projede `src/core` konumunda, genellikle
Git submodule olarak bulunmasıdır:

```bash
git submodule add https://github.com/TahsinCr/vehicle-autonomy-core.git src/core
```

```python
from src.core import DependencyContainer, EventBus, MissionEngine
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime
```

Relative package importları sayesinde checkout başka bir üst paket adı altında da
kullanılabilir.

## Hızlı başlangıç

### Dependency injection

```python
from src.core import DependencyContainer

with DependencyContainer() as container:
    container.singleton(str, instance="vehicle-01")
    assert container.resolve(str) == "vehicle-01"
```

Provider veya cleanup metodu asenkron ise `async with` kullanın.

### Event

```python
from src.core import EventBus

with EventBus[str](history=32) as events:
    subscription = events.subscribe(print)
    events.publish("ready")
    subscription.cancel()
```

`AsyncEventBus`, async handler ve lifecycle metotlarıyla aynı yapının
asyncio-native karşılığını sunar.

### Mission

```python
from src.core import Mission, MissionEngine

class HealthCheck(Mission):
    def start(self) -> None:
        self.complete({"healthy": True})

    def stop(self) -> None:
        pass

with MissionEngine() as engine:
    snapshot = engine.run(HealthCheck())
    result = engine.wait(snapshot.mission_id, timeout=2.0)
```

Mission callback'leri mission worker'larında çalışır. Transition, resource
arbitration, queue, retry ve terminal cleanup engine tarafından yönetilir.

### MAVLink

```python
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime

endpoint = MavlinkEndpoint.udp("0.0.0.0", 14550)

with MavlinkRuntime(endpoint) as link:
    vehicle = link.vehicles.wait_for(timeout=5.0)
    if vehicle is not None:
        vehicle.subscribe("GLOBAL_POSITION_INT", print)
```

Her fiziksel bağlantıyı tek bir router thread'i okur. Kullanıcı callback'leri
bounded worker'larla teslim edildiği için yavaş callback'ler paket okumasını
engellemez. Asyncio uygulamalarında `AsyncMavlinkRuntime`, `async with` ile
kullanılır; public işlemler senkron runtime ile aynıdır ve gerektiğinde await edilir.

## Dokümantasyon

Kapsamlı rehber [`docs/tr/`](docs/tr/README.md) altındadır:

- [Başlangıç](docs/tr/getting-started.md)
- [Mimari](docs/tr/architecture.md)
- [Core yapıları](docs/tr/core.md)
- [Dependency injection](docs/tr/dependency.md)
- [Event](docs/tr/events.md)
- [Mission orchestration](docs/tr/mission.md)
- [MAVLink](docs/tr/mavlink.md)
- [Uygulama protokolü](docs/tr/application-protocol.md)
- [Operasyon ve performans](docs/tr/operations.md)
- [Public API referansı](docs/tr/api-reference.md)

Her sayfadan aynı konunun İngilizce karşılığına geçilebilir.

## Doğrulama

```bash
python run_tests.py
python -m compileall .
python run_stress_tests.py
python run_benchmarks.py
```

Benchmark sonuçları makineye bağlı yazılım regresyonu araçlarıdır; hard-real-time
garantisi değildir. Baseline'ları aynı Python sürümü ve donanımda karşılaştırın.
Çalışmalar `benchmark-logs.json` içinde kaydedilir; kabul sınırları ve seçenekler
operasyon rehberinde açıklanır.

## Katkı

Araca özel davranışları core dışında tutun. Sürekli akışlarda bounded
queue veya retention politikası kullanılmalı; thread, event loop, subscription
ve I/O sahipliği açık olmalıdır. Davranış değişikliklerine deterministik
lifecycle ve hata yolu testleri ekleyin.

Sürüm notları [CHANGELOG.md][changelog-url] dosyasındadır.

## Lisans

Copyright © 2026 TahsinCr.

Yalnızca GNU General Public License v3.0 (`GPL-3.0-only`) ile lisanslanmıştır.
[LICENSE][license-url] ve [COPYRIGHT][copyright-url] dosyalarına bakın.

[python-shield]: https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white
[license-shield]: https://img.shields.io/github/license/TahsinCr/vehicle-autonomy-core.svg?style=for-the-badge
[python-url]: https://www.python.org/downloads/
[readme-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/README.md
[changelog-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/CHANGELOG.md
[license-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/LICENSE
[copyright-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/COPYRIGHT
