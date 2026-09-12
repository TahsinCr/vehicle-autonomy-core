[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/getting-started.md) | **Türkçe**

# Başlangıç

## Kurulum

Core, dependency, event ve mission özellikleri için:

```bash
python -m pip install .
```

MAVLink taşıması için:

```bash
python -m pip install '.[mavlink]'
```

Depo genellikle `src/core` altında submodule olarak kullanılır:

```text
uygulama/
├── src/
│   ├── core/       # bu depo
│   └── ...
└── tests/
```

Bu depoda doğrudan `python run_tests.py` çalıştırılabilir. `dependency`,
`events`, `mission` veya `mavlink` klasörlerini ayrı ayrı `PYTHONPATH` içine
eklemeyin; import'u paket kökünden yapın.

## İlk event

```python
from src.core import EventBus

with EventBus[str](history=20) as events:
    subscription = events.subscribe(print)
    result = events.publish("hazır")
    assert result.successful
    subscription.cancel()
```

## İlk dependency container

```python
from src.core import DependencyContainer

class Clock:
    def now(self) -> float:
        ...

container = DependencyContainer()
container.singleton(Clock)

with container:
    clock = container.resolve(Clock)
```

Context manager `shutdown()` çağırır ve cache'lenen kaynakları kapatır. Provider
veya cleanup async ise `async with` kullanın.

## İlk mission

```python
from src.core import Mission, MissionEngine

class ArmMission(Mission):
    def start(self) -> None:
        self.complete({"armed": True})

    def stop(self) -> None:
        pass

with MissionEngine() as engine:
    snapshot = engine.run(ArmMission)
    finished = engine.wait(snapshot.mission_id, timeout=2.0)
    assert finished is not None and finished.phase.terminal
```

Uygulama mantığı `Mission.start()`, `stop()` ve gerekirse `tick()` içinde yer
alır. State transition, zamanlama ve resource arbitration engine'e aittir.

## İlk MAVLink runtime

```python
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime

endpoint = MavlinkEndpoint.udp("0.0.0.0", 14550)

with MavlinkRuntime(endpoint) as link:
    vehicle = link.vehicles.wait_for(timeout=5.0)
    if vehicle is not None:
        vehicle.subscribe("GLOBAL_POSITION_INT", print)
        vehicle.request_message_rate(
            "GLOBAL_POSITION_INT",
            frequency_hz=10.0,
        )
```

`with` bittiğinde monitor, router ve connection bağımlılık sırasıyla kapanır.

## Async runtime

```python
import asyncio
from src.core.mavlink import AsyncMavlinkRuntime, MavlinkEndpoint

async def main() -> None:
    async with AsyncMavlinkRuntime(MavlinkEndpoint.udp("0.0.0.0", 14550)) as link:
        vehicle = await link.vehicles.wait_for(timeout=5.0)
        if vehicle is not None:
            await vehicle.request_message_rate("ATTITUDE", 20.0)

asyncio.run(main())
```

Ayrı `.aio` görünümü yoktur. Async runtime'ın keşfettiği nesnelerin taşıma
işlemleri await edilir; sync runtime nesneleri normal çağrı sunar.
