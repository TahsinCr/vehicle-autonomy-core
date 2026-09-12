**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/README.md)

# Vehicle Autonomy Core documentation

This documentation describes the public API of Vehicle Autonomy Core v1.7.
The library is vehicle-agnostic: it provides reusable dependency management,
events, mission orchestration and MAVLink transport without embedding UI or
vehicle-specific mission logic.

## Documentation map

- [Getting started](getting-started.md) — installation, source layout and first programs
- [Architecture](architecture.md) — module boundaries, threading and ownership
- [Core abstractions](core.md) — `Model`, `Service` and serialization
- [Dependency injection](dependency.md) — registration, resolution, scopes and cleanup
- [Events](events.md) — sync/async buses, callbacks, hooks, replay and engines
- [Missions](mission.md) — mission implementations, scheduling and orchestration
- [MAVLink](mavlink.md) — connections, routing, vehicles, history and async runtime
- [Application protocol](application-protocol.md) — fragmented packets, peers and dispatch
- [API index](api-reference.md) — every supported public symbol by package
- [Operations and testing](operations.md) — shutdown, observability, tests and benchmarks

## Import conventions

Consumer projects normally install this repository at `src/core` and import:

```python
from src.core import DependencyContainer, EventBus, Mission, MissionEngine
from src.core.mavlink import MavlinkEndpoint, MavlinkRuntime
```

The package uses relative imports internally, so another parent package name is
also supported. MAVLink APIs are not re-exported from the root package.

## Compatibility

- Python 3.10 or newer
- `pymavlink` is optional until MAVLink transport is used
- Sync and async APIs remain separate where Python requires different call semantics
- Frozen snapshot models return detached data and are safe to pass between readers

The source code is authoritative when documentation and an unreleased checkout
diverge. Released documentation applies to v1.7 unless a page says otherwise.
