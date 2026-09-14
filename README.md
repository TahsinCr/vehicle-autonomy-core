[![Python 3.10+][python-shield]][python-url]
[![Repository license][license-shield]][license-url]

**English** | [Türkçe][readme-tr-url]

# Vehicle Autonomy Core

Vehicle Autonomy Core is a reusable Python foundation for autonomous vehicle
projects. It provides dependency injection, synchronous and asynchronous
events, mission orchestration, and MAVLink communication without embedding
vehicle-specific behavior.

It is a toolkit rather than a finished autonomy application. Guidance,
navigation, payload logic, computer vision, UI, and product-specific mission
decisions belong in the application using the core.

## What is included

- Lightweight `Model` and `Service` contracts
- Scoped dependency injection with deterministic sync and async cleanup
- Thread-safe and asyncio-native event buses
- Mission scheduling, resources, priorities, retries, chains, parallel groups,
  and background missions
- A single-reader MAVLink router with vehicle and component discovery
- Sync and async runtimes with bounded callback delivery
- Optional message history, application packets, request/response, and remote
  logging models

## Requirements and installation

Python 3.10 or newer is required. `pymavlink` is optional and is only needed
when opening a real MAVLink connection.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

```bash
python -m pip install -e '.[mavlink]'
```

## Repository layout

The intended consumer layout places this repository at `src/core`, commonly as
a Git submodule:

```bash
git submodule add https://github.com/TahsinCr/vehicle-autonomy-core.git src/core
```

```python
from src.core import DependencyContainer, EventBus, MissionEngine
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime
```

Relative package imports also allow the checkout to live below another parent
package name.

## Quick start

### Dependency injection

```python
from src.core import DependencyContainer

with DependencyContainer() as container:
    container.singleton(str, instance="vehicle-01")
    assert container.resolve(str) == "vehicle-01"
```

Use `async with` when providers or cleanup methods are asynchronous.

### Events

```python
from src.core import EventBus

with EventBus[str](history=32) as events:
    subscription = events.subscribe(print)
    events.publish("ready")
    subscription.cancel()
```

`AsyncEventBus` provides the equivalent asyncio-native interface with async
handlers and lifecycle methods.

### Missions

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

Mission callbacks run on mission workers. The engine owns transitions,
resource arbitration, queueing, retries, and terminal cleanup.

### MAVLink

```python
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime

endpoint = MavlinkEndpoint.udp("0.0.0.0", 14550)

with MavlinkRuntime(endpoint) as link:
    vehicle = link.vehicles.wait_for(timeout=5.0)
    if vehicle is not None:
        vehicle.subscribe("GLOBAL_POSITION_INT", print)
```

One router thread owns reads from each physical connection. User callbacks are
delivered through bounded workers, so slow callbacks do not block packet reads.
Use `AsyncMavlinkRuntime` with `async with` for asyncio applications; its public
operations mirror the synchronous runtime and are awaited where necessary.

## Documentation

The complete guide lives in [`docs/en/`](docs/en/README.md):

- [Getting started](docs/en/getting-started.md)
- [Architecture](docs/en/architecture.md)
- [Core abstractions](docs/en/core.md)
- [Dependency injection](docs/en/dependency.md)
- [Events](docs/en/events.md)
- [Mission orchestration](docs/en/mission.md)
- [MAVLink](docs/en/mavlink.md)
- [Application protocol](docs/en/application-protocol.md)
- [Operations and performance](docs/en/operations.md)
- [Public API reference](docs/en/api-reference.md)

Each page links to its Turkish counterpart.

## Verification

```bash
python run_tests.py
python -m compileall .
python run_stress_tests.py
python run_benchmarks.py
```

Benchmark results are machine-dependent regression probes, not hard-real-time
guarantees. Compare baselines produced with the same Python build and hardware.

## Contributing

Keep vehicle-specific behavior outside the core. Continuous paths must use
bounded queues or retention policies, and ownership of threads, event loops,
subscriptions, and I/O must remain explicit. Add deterministic lifecycle and
failure-path tests with behavioral changes.

Release notes are available in [CHANGELOG.md][changelog-url].

## License

Copyright © 2026 TahsinCr.

Licensed under GNU General Public License v3.0 only (`GPL-3.0-only`). See
[LICENSE][license-url] and [COPYRIGHT][copyright-url].

[python-shield]: https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white
[license-shield]: https://img.shields.io/github/license/TahsinCr/vehicle-autonomy-core.svg?style=for-the-badge
[python-url]: https://www.python.org/downloads/
[readme-tr-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/README-TR.md
[changelog-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/CHANGELOG.md
[license-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/LICENSE
[copyright-url]: https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/COPYRIGHT
