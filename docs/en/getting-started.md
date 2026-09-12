**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/getting-started.md)

# Getting started

## Install

For core, dependency, event and mission features:

```bash
python -m pip install .
```

For MAVLink transport support:

```bash
python -m pip install '.[mavlink]'
```

The repository is commonly used as a submodule at `src/core`:

```text
application/
├── src/
│   ├── core/       # this repository
│   └── ...
└── tests/
```

Run directly from this repository with `python run_tests.py`. Do not add the
individual `dependency`, `events`, `mission` or `mavlink` directories to
`PYTHONPATH`; import through the package root.

## Minimal event program

```python
from src.core import EventBus

with EventBus[str](history=20) as events:
    subscription = events.subscribe(print)
    result = events.publish("ready")
    assert result.successful
    subscription.cancel()
```

## Minimal dependency container

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

The context manager calls `shutdown()` and disposes cached resources. Use
`async with` when providers or cleanup methods are asynchronous.

## Minimal mission

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

`Mission.start()`, `stop()` and optionally `tick()` contain application logic.
The engine owns state transitions, timing and resource arbitration.

## Minimal MAVLink runtime

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

The `with` block stops the vehicle monitor, router and connection in dependency
order. Callbacks do not run after runtime shutdown completes.

## Async MAVLink runtime

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

There is no separate `.aio` view. Objects discovered by an async runtime expose
awaitable transport operations; objects from a sync runtime expose sync ones.

## Next steps

- Learn ownership and thread rules in [Architecture](architecture.md).
- Configure callbacks in [Events](events.md).
- Build chains and parallel missions in [Missions](mission.md).
- Configure multi-vehicle state and recording in [MAVLink](mavlink.md).
