[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/operations.md) | **Türkçe**

# Operasyon, test ve performans

## Kapanış kontrol listesi

Kaynak sahipliğini context manager'larla açıkça kurun:

```python
with DependencyContainer() as dependencies:
    with MessageHistory(background=True) as history:
        with MavlinkRuntime(endpoint) as link:
            link.add_history(history)
            ...
```

Async kaynaklarda `async with` ve `shutdown_async()` kullanın. Async-only cleanup
içeren container'ı senkron kapatmayın. Cleanup hata verirse sahibi korunur;
alttaki hata düzeltildikten sonra işlem yeniden denenebilir.

Mission cleanup hatası başarıya dönüştürülmez. Mission `STOPPING` durumunda
kalır ve `stop()` başarılı olana kadar kaynak sahipliğini bırakmaz.

## Kapasite planlama

| Alan | Sınır | Sınır aşılınca |
|---|---|---|
| Event periyodik işleri | `max_schedules` | kayıt hatası |
| Replay bekleyen event'leri | `replay_buffer_limit` | ilgili abonelik iptal edilir ve hata raporlanır |
| Runtime telemetri callback'leri | `callback_capacity` / `delivery_capacity` | en eski telemetri callback'i düşürülür ve sayılır |
| Runtime lifecycle aksiyonları | `callback_action_capacity` / `action_capacity` | fatal delivery hatası |
| Application dispatcher | `max_pending` | dispatch reddedilir |
| History writer | `queue_capacity` | açık kayıt hatası |
| Router latest state | `state_capacity` | LRU eviction |
| Router source condition map'leri | `source_capacity` | LRU source eviction |
| Araç durumu | `vehicle_state_retention` | disconnected state süre sonunda kaldırılır |
| Cache | `per_key_limit`, `max_keys` | en eski kayıt/key çıkarılır |

Kapasiteyi yalnız mesaj frekansına göre seçmeyin. Beklenen en uzun callback veya
storage duraklamasını ve güvenlik payını hesaba katın.

## Gözlemlenebilirlik

- `EventBus.stats`: yayınlanan, teslim edilen ve başarısız event sayısı.
- `MavlinkRuntime.state`: lifecycle, bağlantı, peer ve router durumu.
- `MavlinkMessageRouter.stats`: receive/filter/dispatch/loss/state sayaçları.
- `MavlinkRuntime.dropped_callbacks`: callback backpressure sayısı.
- `MavlinkRuntime.delivery_error`: fatal callback teslim hatası.
- `MessageCache.stats`: key, tutulan mesaj ve çıkarılan key sayısı.
- `MessageHistory.writer_stats`: gönderilen, işlenen, kalıcı yazılan, başarısız,
  kuyruktaki kayıt ve batch sayaçları ile hata durumu.
- `MessageHistory.recording_error`: özgün writer exception'ı.
- `MavlinkApplicationPeer.state`: liveness, RTT ve paket sayaçları.
- `MissionEngine.manager_snapshot()`: aktif/kuyruktaki/duraklatılmış mission'lar ve kaynak sahipleri.
- `MissionEngine.query_events()`: saklanan yapısal mission event'leri.

Snapshot property'leri güvenle okunabilir; gereksiz derecede sık polling yapmayın.

## SQLite önerileri

Eksiksiz arşiv gerekmiyorsa gömülü depolamada sınırlı retention kullanın.
`wal=True`, eşzamanlı okuma/yazmayı iyileştirir fakat WAL yan dosyaları oluşturur;
bu nedenle opsiyoneldir. `busy_timeout`, SQLite'ın kilit için bekleme süresidir.
Batch boyutu ile flush aralığı, gecikme ve transaction verimi arasındaki dengeyi
belirler.

`recording_error` veya runtime history hatalarını mutlaka izleyin. MAVLink
mesajının alınması, kalıcı kaydın başarılı olduğu anlamına gelmez.

## Test komutları

Tüm suite'i çalıştırın:

```bash
python run_tests.py
```

Standart discovery karşılığı:

```bash
python -m unittest discover -v
```

Syntax/import derlemesini doğrulayın:

```bash
python -m compileall -q .
```

Geliştirme kalite kapılarını kurup çalıştırın:

```bash
python -m pip install -e ".[quality]"
ruff check .
pyright
coverage run run_tests.py
coverage report
python run_stress_tests.py --repeats 25
```

Coverage branch kararlarını da ölçer ve proje genelinde %82 taban sınırı
uygular. Pyright ilk aşamada production modüllerindeki kesin isim ve kontrol
akışı hatalarını denetler; bu kademeli başlangıç dinamik provider/callback
yapılarını geniş cast'lerle gizlemez. Stress runner seçilen concurrency
regresyonlarını her turda yeni suite ile tekrarlar.

CI matrisi desteklenen Python sürümlerini çalıştırır ve wheel üretir. Testler
hem bağımsız checkout'u hem amaçlanan `src/core` submodule yerleşimini kapsar.

## Benchmark

```bash
python run_benchmarks.py
python run_benchmarks.py --quick --json > benchmark.json
python run_benchmarks.py --quick --compare benchmark.json
python run_benchmarks.py --load-profile normal --load-storage sqlite
```

Benchmark; wall time, CPU time, işlem başına tutulan byte ve geçici peak
allocation değerlerini raporlar. Core model serialization, sync/async event,
dependency resolution, MAVLink filter/cache/routing/application packet ve
mission işlemlerini kapsar.

Bu değerler karşılaştırma içindir; hard real-time garantisi değildir. Aynı
interpreter, CPU governor ve sistem yüküyle karşılaştırma yapın. Başka bir
makinenin sabit mikrosaniye eşiği yerine oranlara ve dağılım eğilimine bakın.

`--compare`, sabit işlem adlarını eşleştirir ve
`--max-regression-percent` değiştirilmezse önce suite genelindeki sistem hızı
farkını kalibre eder, sonra işleme özel maliyetteki %40 üzeri artışı
reddeder. Regresyonun hem wall hem CPU zamanında görülmesi gerekir; bu,
tutarlı kod yolu yavaşlamasını saklamadan runner scheduling gürültüsünü
süzer. Paylaşımlı CI işlemci tahsisi değişken olduğu için CI %60 tolerans,
kontrollü yerel çalıştırma ise daha sıkı %40 varsayılanını kullanır.
Birleşik profiller (`normal`, `medium`, `heavy`, `stress`); routing,
çoklu araç state'i, birden fazla callback ve background memory/SQLite kaydını
aynı anda çalıştırır. Throughput, p50/p95/p99 gecikme, mesaj başına CPU ve
bellek, writer baskısı, başarısız kayıt ve thread artışı raporlanır.

Production kurulumlarında beklenen kaynak sayısı ölçüldükten sonra sonlu
`state_capacity` ve `source_capacity` değerleri açıkça verilmelidir. Geçerli
state'i sessizce çıkarmak her ortamda daha güvenli olmadığı için genel varsayılan
`None` kalır. Dispatcher'da `workers=1` de sıralı varsayılandır; yalnız bağımsız
ve thread-safe handler'lar için artırılmalıdır.

## Donanım ve entegrasyon doğrulaması

Saha veya uçuş öncesinde uygulama katmanında şunları ayrıca test edin:

- gerçek serial/UDP reconnect ve bozuk trafik;
- aynı anda birden fazla vehicle system ID;
- beklenen sürekli telemetri hızı ve burst payı;
- dolu veya yavaş storage davranışı;
- callback ve mission cleanup hataları;
- request beklerken process kapanışı;
- SITL/HIL mission geçişleri ve aktüatör güvenliği;
- memory/state sayaçlarını izleyen uzun süreli soak testleri.

Core unit testleri yazılım sözleşmelerini doğrular; araç, taşıma ve işletim
sistemi doğrulamasının yerini tutmaz.
