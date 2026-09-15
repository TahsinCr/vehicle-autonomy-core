[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/mission.md) | **Türkçe**

# Mission orkestrasyonu

Mission modülü uygulamanın tanımladığı işi çalıştırırken transition, priority,
prerequisite, conflict, retry, timing ve cleanup'ı yönetir. Araca özel mantık
subclass'ta kalır.

## Okuma akışı

```text
Mission instance oluştur → run → durumu izle → resource ve priority
                        → chain/parallel/background → cleanup ve recovery
```

Mission açıkça oluşturulup yapılandırıldıktan sonra `run(instance)` kullanılır.
Admission izin verdiğinde bağımsız mission'lar doğal olarak eşzamanlı çalışır.
`run_parallel()` ise tek bir tracked aggregate execution oluşturur.

## Tam bir sağlık kontrolü örneği

```python
from src.core import Mission, MissionEngine, MissionPhase

class SensorGateway:
    def all_ready(self) -> bool:
        return True

class SystemCheck(Mission):
    resources = frozenset({"sensor-health"})
    timeout_seconds = 2.0

    def __init__(self, sensors: SensorGateway) -> None:
        super().__init__()
        self.sensors = sensors

    def start(self) -> None:
        self.checkpoint("sensor-scan", attempted=True)
        if not self.sensors.all_ready():
            self.fail("Gerekli bir sensöre ulaşılamıyor", retryable=True)
        self.update_progress(1.0, reason="Tüm sensörler cevap verdi")
        self.complete({"ready": True})

    def stop(self) -> None:
        pass

sensors = SensorGateway()
engine = MissionEngine()

with engine:
    started = engine.run(SystemCheck())
    finished = engine.wait(started.mission_id, timeout=3.0)
    assert finished is not None
    assert finished.phase is MissionPhase.SUCCEEDED
```

Sensor adapter'ını application verir; core yalnızca mission'ı oluşturur,
schedule eder ve izler. Checkpoint ile progress, engine sensör domain'ini
bilmeden snapshot'ta görünür kalır.

## Mission tanımlama

```python
from src.core import Mission, MissionConflictPolicy, MissionPriority
from src.core.mission import MissionRetryPolicy

class SurveyMission(Mission):
    priority = MissionPriority.NORMAL
    resources = frozenset({"navigation"})
    tags = frozenset({"survey"})
    conflict_policy = MissionConflictPolicy.QUEUE
    tick_interval = 0.1
    timeout_seconds = 120.0
    retry = MissionRetryPolicy(attempts=2, delay=1.0)

    def start(self) -> None:
        self.vehicle = ...

    def tick(self, elapsed_seconds: float) -> None:
        if self.finished():
            self.complete({"images": 24})

    def stop(self) -> None:
        self.vehicle.hold()
```

Class ayarları:

| Alan | Varsayılan | Anlamı |
|---|---:|---|
| `priority` | `NORMAL` | Küçük sayı daha yüksek yetki |
| `resources` | boş | Özel sahiplenilen resource adları |
| `blocks` | boş | Conflict oluşturulan mission tipleri |
| `tags` | boş | Grup kontrol etiketleri |
| `prerequisites` | boş | Önce başarılı olması gereken mission tipleri |
| `conflict_policy` | `REJECT` | Reject, queue veya düşük priority preemption |
| `prerequisite_policy` | `REJECT` | Eksik prerequisite için reject/queue |
| `tick_interval` | `0.1` | Tick aralığı, saniye |
| `timeout_seconds` | `None` | Çalışma timeout'u |
| `queue_timeout_seconds` | `None` | Kuyrukta kalma timeout'u |
| `retry` | 1 deneme | `MissionRetryPolicy(attempts, delay)` |

`Mission(name=None)` UUID tabanlı benzersiz integer `id` oluşturur. Varsayılan
name doğrudan somut class adıdır ve instance için değiştirilebilir.

`MissionNode(name, mission)`, mission'ın kendi adını değiştirmeden
yapılandırılmış instance'a sabit bir execution anahtarı verir. Instance chain
veya group'a doğrudan konursa node anahtarı olarak mission adı kullanılır.
Node, chain, group veya execution snapshot üzerinde `to_dict()` çağrıldığında
canlı mission; `id`, `name` ve somut `type` bilgileriyle temsil edilir. Runtime
lock'ları, transport ve controller state'i serileştirme sırasında kopyalanmaz.

Gerekli metotlar `start()` ve `stop()`; opsiyonel hook'lar `pause()`, `resume()`,
`tick(elapsed_seconds)`. Mission içinden `complete(result=None)`,
`fail(reason, retryable=False)`, `checkpoint(name, **values)`,
`update_progress(value, reason="")`, `wait_for_stop(timeout=None)` ve
`stop_missions(tags=(), resources=())` kullanılabilir.

`bind_control`/`unbind_control` engine wiring içindir. `id`, `name`, `control`,
`runtime`, `stop_requested` okunabilir. Lifecycle callback'i içindeki
complete/fail ve mission'ın kendisine verdiği stop/cancel komutları, callback
kilidi bırakıldıktan sonra güvenle tamamlanır. Mevcut terminal komutuyla aynı
anda callback hatası oluşursa ilk intent korunur ve asıl hata error event olarak
yayınlanır.
`stop()` hata verirse mission `STOPPING` kalır, resource'u korur ve
`MissionCleanupError` verir.

## `MissionEngine`

```text
MissionEngine(*, scheduler_interval=0.05, stop_timeout=2.0,
              event_history=1000, execution_history=256,
              max_active_missions=None, max_queued_missions=None,
              lifecycle=None, scheduler=None)
```

Doğrudan, chain ve parallel çalıştırmalarının tamamında yapılandırılmış mission
instance'ları verilir. Custom lifecycle/scheduler engine'e bağlanır.

Kayıt ve çalıştırma:

- `register(mission)`, `unregister(reference)`, `mission(reference)`
- `run(mission, *missions, requester_id=None, reason="")`: bir veya daha fazla
  hazır instance'ı birbirinden bağımsız çalıştır
- `run_parallel(group)`: takip edilen bir `MissionParallelGroup` çalıştır
- `wait(reference, timeout=None)`

Aynı instance tek bir `run()` çağrısına iki kez verilemez. Duplicate girdiler
hiçbir mission admission'a alınmadan önce `ValueError` üretir.

Çoklu girdiler bağımsızdır ve argüman sırasıyla admission'a alınır. Sonraki bir
mission reddedilirse öncekiler çalışmaya devam eder, daha sonraki girdiler
denenmez. Reddedilen mission gözlem veya sonraki bir deneme için kayıtlı kalır.
İşlem bilinçli olarak transactional değildir.

Terminal cleanup sırasında ilk kabul edilen sonuç thread'ler arasında da
belirleyicidir. Cleanup callback'i aynı terminal komutu doğrudan veya beklediği
bir yardımcı thread üzerinden verebilir; finalization yeniden başlatılmaz.
Çelişen terminal komutlar reddedilmeye devam eder.

Lifecycle: `pause`, `resume`, `stop_mission`, `cancel` requester/reason alır;
`complete`, `fail`, `progress`, `checkpoint` seçilen mission'ı günceller.
`stop_matching(requester_id, tags=(), resources=())`, aktif requester'ın somut
ID bilmeden düşük yetkili işi durdurmasını sağlar.

Herhangi bir terminal komut veya yakalanmamış worker hatası sırasında cleanup
tamamlanamazsa ilk terminal phase, ayrılmış result, reason ve retry bilgisi korunur.
Bu davranış callback içinden ve dışarıdan verilen lifecycle çağrıları için
geçerlidir. İlk terminal intent kazanır; beklerken çelişen komut reddedilir. Neden
giderildikten sonra `retry_cleanup(reference)` cleanup'ı ve aynı terminal
niyeti yeniden yürütür.

Eksik engine shutdown sonrasında `stop()` yeniden çağrılabilir. Mission ve
scheduler cleanup tamamlandığında stopping durumu temizlenir ve engine yeniden
başlatılabilir. `close()` da engine'i closed işaretleyip mission state'ini
bırakmadan önce event kanallarının kapanmasını yeniden deneyebilir; başarısız
close girişimleri arasında stopping kalır ve yeni işi reddeder.

State API'si: `snapshot`, `snapshots`, `manager_snapshot`, `query_events`,
`events`, `transitions`, `stopping`. `MissionSnapshot` alanları: `mission_id`,
`name`, `phase`, `generation`, `attempt`, `progress`, `reason`, `result`,
`checkpoints`, `registered_at`, `queued_at`, `next_retry_at`, `started_at`,
`updated_at`, `finished_at`, `cleanup_pending`, `cleanup_error`.
`evolve(**changes)` replacement üretir;
`duration_seconds` süreyi verir.

## Chain

`MissionChain(chain_id, stages, stop_on_failure=True)` yapılandırılmış
instance'ları sıralı çalıştırır. Stage; `Mission`, `MissionNode` veya
`MissionParallelStage` olabilir.
Plan bu instance'ların sahibidir; ayrı bir execution için yeni instance'larla
yeni bir plan oluşturulur.

```python
chain = MissionChain(
    "inspection",
    (
        TakeoffMission(),
        MissionParallelStage(
            "inspect",
            (MissionNode("camera", CameraMission()),
             MissionNode("mapping", MappingMission())),
            failure_policy=ParallelFailurePolicy.CANCEL_REMAINING,
        ),
        LandMission(),
    ),
)
execution = engine.run_chain(chain, input={"altitude": 30})
finished = engine.wait_chain("inspection", timeout=180.0)
```

API: `run_chain`, `chain_snapshot`, `wait_chain`, `stop_chain`, `cancel_chain`,
`forget_chain`. `MissionChainSnapshot.current_stage` aktif stage'i verir.

`MissionExecutionContext` alanları: `chain_id`, `execution_id`, `current_index`,
`input`, `metadata`, `previous_mission`, `previous_result`, `results`.
`MissionController.chain_context()` bunu running mission'a açar.
`MissionExecutionResult(node, mission_id, phase, result)` stage sonucudur;
parallel stage için `mission_id=None` olur.

## Parallel ve background

`MissionParallelGroup(group_id, nodes, failure_policy=WAIT_ALL)` için
`run_parallel`, `parallel_snapshot`, `wait_parallel`, `stop_parallel`,
`cancel_parallel`, `forget_parallel` kullanılır. Snapshot; group, execution ID,
lifecycle flag'leri, children, phases, results ve reason taşır.
Group tek execution için yapılandırılmış instance'ların sahibidir. Yeniden
çalıştırmak için yeni instance'larla yeni bir group oluşturulur.

```python
background = engine.run_background(
    HealthMonitorMission(),
    owner=chain_snapshot,
    termination_policy=OwnerTerminationPolicy.STOP_WITH_OWNER,
    failure_policy=BackgroundFailurePolicy.FAIL_OWNER,
)
```

Owner mission/ID/chain/parallel snapshot olabilir. `background_snapshot(id)`
ilişkiyi okur. Owner policy: `STOP_WITH_OWNER`, `CANCEL_WITH_OWNER`,
`KEEP_RUNNING`. Failure policy: `IGNORE`, `FAIL_OWNER`, `STOP_EXECUTION`.

## Phase, priority ve event

`MissionPhase`: `REGISTERED`, `QUEUED`, `STARTING`, `RUNNING`, `PAUSING`,
`PAUSED`, `STOPPING`, `STOPPED`, `SUCCEEDED`, `FAILED`, `CANCELLED`; `.active`
ve `.terminal` property'leri vardır.

`MissionPriority`: `CRITICAL=0`, `HIGH=100`, `NORMAL=500`, `LOW=900`,
`BACKGROUND=1000`. `MissionConflictPolicy`: `REJECT`, `QUEUE`, `PREEMPT_LOWER`.
`MissionPrerequisitePolicy`: `REJECT`, `QUEUE`. `ParallelFailurePolicy`:
`WAIT_ALL`, `CANCEL_REMAINING`, `STOP_REMAINING`.

`ensure_mission_transition(previous, current)` transition'ı doğrular.
`MissionTransition` mission ID, önceki/yeni phase, requester, reason ve timestamp taşır.

`MissionEvent` alanları: `event_type`, `message`, `level`, `mission_id`,
`requester_id`, `generation`, `fields`, `sequence`, `timestamp`.
`MissionEventType`: `MANAGER`, `REGISTERED`, `UNREGISTERED`, `COMMAND`,
`TRANSITION`, `PROGRESS`, `CHECKPOINT`, `CHAIN`, `PARALLEL`, `BACKGROUND`,
`RETRY`, `LOG`, `ERROR`. `MissionEventLevel`: DEBUG/INFO/WARNING/ERROR/CRITICAL.
`MissionEventQuery` mission ID, event type, minimum level, sequence ve limit filtreler.

`MissionManagerSnapshot` running durumunu, registered/active/queued/paused ID'leri,
resource owner'larını ve update zamanını taşır. `MissionBackgroundSnapshot` owner
bilgisini ve policy'leri taşır.

## Genişletme ve hatalar

`MissionController` abstract komut yüzeyidir. `MissionLifecycle` lifecycle,
`MissionScheduler` çalıştırma admission policy'sini uygular; ikisi de
`bind(engine)` sunar ve
gerektiğinde subclass edilebilir.

Hatalar: `MissionError`, `MissionRegistrationError`, `MissionPermissionError`,
`MissionConflictError`, `MissionNotFoundError`, `MissionTimeoutError`,
`MissionCleanupError`, `MissionTransitionError`.
