"""Benchmark core modules with normalized per-operation values.

Run from either a standalone checkout or a ``src/core`` submodule layout::

    python run_benchmarks.py
    python run_benchmarks.py --quick
    python run_benchmarks.py --json

This is a regression probe, not a claim about absolute hardware performance.
Compare results produced on the same machine and Python build.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib.util
import json
import platform
import statistics
import sys
import time
import tracemalloc
import types
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Awaitable, Callable


ROOT = Path(__file__).resolve().parent


def _load_standalone_checkout() -> None:
    """Expose a standalone checkout under its intended ``src.core`` name."""

    try:
        import src.core  # noqa: F401
    except ModuleNotFoundError:
        src = sys.modules.get("src")
        if src is None:
            src = types.ModuleType("src")
            src.__path__ = []  # type: ignore[attr-defined]
            sys.modules["src"] = src
        spec = importlib.util.spec_from_file_location(
            "src.core",
            ROOT / "__init__.py",
            submodule_search_locations=[str(ROOT)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load the core package")
        module = importlib.util.module_from_spec(spec)
        sys.modules["src.core"] = module
        spec.loader.exec_module(module)


_load_standalone_checkout()

from src.core import Model  # noqa: E402
from src.core.dependency import DependencyContainer  # noqa: E402
from src.core.events import (  # noqa: E402
    AsyncEventBus,
    EventBus,
    EventFilter,
    MemoryEventHistory,
)
from src.core.mavlink import (  # noqa: E402
    MavlinkApplicationAssembler,
    MavlinkApplicationCodec,
    MavlinkApplicationPacket,
    MavlinkEndpoint,
    MavlinkMessageEnvelope,
    MavlinkMessageFilter,
    MavlinkMessageRouter,
    MavlinkRemoteLogBatch,
    MavlinkRemoteLogRecord,
    MessageCache,
)
from src.core.mission import (  # noqa: E402
    Mission,
    MissionEngine,
    MissionPhase,
    MissionSnapshot,
)
from src.core.mavlink.vehicles import VehicleRegistry  # noqa: E402
from src.core.mavlink.handlers import ApplicationHandlers  # noqa: E402


Operation = Callable[[], object]
AsyncOperation = Callable[[], Awaitable[object]]


@dataclass(slots=True)
class BenchmarkCase:
    category: str
    name: str
    operation: Operation
    iterations: int
    cleanup: Callable[[], None] = lambda: None


@dataclass(slots=True)
class AsyncBenchmarkCase:
    category: str
    name: str
    operation: AsyncOperation
    iterations: int


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    category: str
    name: str
    iterations: int
    wall_ns_per_op: float
    cpu_ns_per_op: float
    relative_to_noop: float
    retained_bytes_per_op: float
    peak_bytes_per_op: int


class _TinyService:
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class _BenchmarkModel(Model):
    name: str
    payload: object


class _IdleMission(Mission):
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _CompletingMission(_IdleMission):
    def start(self) -> None:
        self.complete({"done": True})


class _MavlinkMessage:
    __slots__ = ()

    def get_type(self) -> str:
        return "HEARTBEAT"

    def get_srcSystem(self) -> int:
        return 1

    def get_srcComponent(self) -> int:
        return 1

    def get_msgId(self) -> int:
        return 0

    def get_seq(self) -> int:
        return 1


class _RouterConnection:
    __slots__ = ()

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def evaluate_condition(self, _condition: str) -> bool:
        return True


class _VehicleMessage(_MavlinkMessage):
    autopilot = 3
    type = 2

    def __init__(self, system):
        self.system = system

    def get_srcSystem(self):
        return self.system


def _vehicle_cases(base_iterations):
    """Compare the same routing operation with different registry sizes."""
    cases = []
    dialect = types.SimpleNamespace(MAV_AUTOPILOT_INVALID=8, MAV_TYPE_GCS=6)
    for size in (1, 10, 100):
        runtime = types.SimpleNamespace(connection=types.SimpleNamespace(mavlink=dialect))
        runtime._application_handlers = ApplicationHandlers(runtime)
        registry = VehicleRegistry(runtime, history_capacity=32)
        registry.running = True
        for system in range(1, size + 1):
            registry.accept(MavlinkMessageEnvelope.wrap(system, _VehicleMessage(system)))
            registry.vehicles.get(system).subscribe("HEARTBEAT", lambda event: None)
        envelope = MavlinkMessageEnvelope.wrap(size + 1, _VehicleMessage(1))
        cases.append(BenchmarkCase(
            "MAVLink", f"source routing with {size} vehicles",
            lambda registry=registry, envelope=envelope: registry.accept(envelope),
            max(100, base_iterations // 5), registry.close,
        ))
    return cases


def build_cases(base_iterations: int) -> list[BenchmarkCase]:
    """Create benchmarks ordered from general primitives to domain features."""
    from src.core.events import CallbackSubscription
    callback = CallbackSubscription(1, lambda: None, lambda event: None)
    hooked = CallbackSubscription(2, lambda: None, lambda event: None,
        predicate=lambda event: True, on_before=lambda context: None,
        on_success=lambda context: None, on_after=lambda context: None)
    disabled = CallbackSubscription(3, lambda: None, lambda event: None, enabled=False)

    model = _BenchmarkModel(
        "parent",
        _BenchmarkModel("child", {"values": tuple(range(16))}),
    )

    history = MemoryEventHistory[int](capacity=1_000)
    for value in range(1_000):
        history.append(value)
    filtered_history: EventFilter[int] = EventFilter(
        predicate=lambda value: value % 7 == 0
    )

    empty_bus = EventBus[int]()
    subscribed_bus = EventBus[int]()
    subscribed_bus.subscribe(lambda _event: None)

    container = DependencyContainer(auto_wire=False)
    container.singleton("singleton", _TinyService)
    container.transient("transient", _TinyService)
    container.scoped("scoped", _TinyService)
    container.resolve("singleton")

    def resolve_scope() -> object:
        scope = container.create_scope()
        try:
            return scope.resolve("scoped")
        finally:
            scope.shutdown()

    packet = MavlinkApplicationPacket(
        "benchmark.telemetry",
        {"position": [41.0, 29.0, 120.0], "armed": True},
        packet_id=1,
    )
    fragment = MavlinkApplicationCodec.encode(packet)[0]
    large_packet = MavlinkApplicationPacket(
        "benchmark.fragments",
        {"payload": "x" * 2_000},
        packet_id=2,
    )
    fragments = MavlinkApplicationCodec.encode(large_packet)

    def assemble_packet() -> object:
        assembler = MavlinkApplicationAssembler()
        result = None
        for item in fragments:
            result = assembler.accept(item, source_system=1, source_component=1)
        return result

    message = _MavlinkMessage()
    message_filter = MavlinkMessageFilter(
        message_types="HEARTBEAT",
        source_systems=1,
        source_components=1,
        message_ids=0,
    )
    cache = MessageCache[tuple[str, int], str](lambda item: item[0])
    for value in range(64):
        cache.add(("HEARTBEAT", value))

    router = MavlinkMessageRouter(_RouterConnection())  # type: ignore[arg-type]
    router.subscribe(lambda _message: None, message_filter)
    envelope = MavlinkMessageEnvelope.wrap(1, message)

    def close_router() -> None:
        router.messages.close()
        router.envelopes.close()
        router.errors.close()

    log_batch = MavlinkRemoteLogBatch(
        "benchmark-session",
        tuple(
            MavlinkRemoteLogRecord(
                sequence=index,
                source="benchmark",
                action="sample",
                message="Core benchmark sample",
                details={"value": index},
            )
            for index in range(1, 9)
        ),
    )

    def cache_cycle() -> object:
        cache.add(("HEARTBEAT", 65))
        return cache.latest("HEARTBEAT")

    snapshot = MissionSnapshot(
        1,
        "Benchmark Mission",
        phase=MissionPhase.RUNNING,
        result={"path": {"points": list(range(16))}},
    )
    engine = MissionEngine(event_history=32)
    for index in range(100):
        engine.register(_IdleMission(name=f"Registered {index}"))

    def mission_registration_cycle() -> object:
        mission = _IdleMission()
        engine.register(mission)
        engine.unregister(mission)
        return mission

    def mission_lifecycle_cycle() -> object:
        mission = _CompletingMission()
        engine.launch(mission)
        result = engine.wait(mission, timeout=1.0)
        engine.unregister(mission)
        return result

    return [
        BenchmarkCase("baseline", "function call", lambda: None, base_iterations),
        BenchmarkCase("events", "callback policy delivery", lambda: callback.invoke(1), base_iterations),
        BenchmarkCase("events", "callback filter and 3 hooks", lambda: hooked.invoke(1), base_iterations),
        BenchmarkCase("events", "disabled callback skip", lambda: disabled.invoke(1), base_iterations),
        BenchmarkCase(
            "abstracts",
            "automatic nested model serialization",
            model.to_dict,
            max(100, base_iterations // 2),
        ),
        BenchmarkCase(
            "core models",
            "snapshot evolve",
            lambda: snapshot.evolve(progress=0.5),
            base_iterations,
        ),
        BenchmarkCase(
            "core models",
            "nested model serialization",
            snapshot.to_dict,
            max(100, base_iterations // 2),
        ),
        BenchmarkCase(
            "events",
            "publish without subscribers",
            lambda: empty_bus.publish(1),
            base_iterations,
            empty_bus.close,
        ),
        BenchmarkCase(
            "events",
            "publish to one subscriber",
            lambda: subscribed_bus.publish(1),
            base_iterations,
            subscribed_bus.close,
        ),
        BenchmarkCase(
            "events",
            "latest from 1,000-item history",
            history.latest,
            base_iterations,
        ),
        BenchmarkCase(
            "events",
            "filtered tail query from history",
            lambda: history.query(filtered_history, limit=10),
            max(100, base_iterations // 2),
        ),
        BenchmarkCase(
            "dependency",
            "cached singleton resolve",
            lambda: container.resolve("singleton"),
            base_iterations,
        ),
        BenchmarkCase(
            "dependency",
            "transient resolve",
            lambda: container.resolve("transient"),
            max(100, base_iterations // 2),
            container.shutdown,
        ),
        BenchmarkCase(
            "dependency",
            "scoped resolve and shutdown",
            resolve_scope,
            max(100, base_iterations // 20),
        ),
        BenchmarkCase(
            "MAVLink",
            "endpoint validation",
            lambda: MavlinkEndpoint.udp("127.0.0.1", 14550),
            max(100, base_iterations // 5),
        ),
        BenchmarkCase(
            "MAVLink",
            "metadata filter match",
            lambda: message_filter.matches(message),
            base_iterations,
        ),
        BenchmarkCase(
            "MAVLink",
            "bounded cache add and latest",
            cache_cycle,
            base_iterations,
        ),
        BenchmarkCase(
            "MAVLink",
            "router dispatch to one route",
            lambda: router._dispatch(envelope),
            max(100, base_iterations // 5),
            close_router,
        ),
        BenchmarkCase(
            "MAVLink application",
            "packet encode",
            lambda: MavlinkApplicationCodec.encode(packet),
            max(100, base_iterations // 10),
        ),
        BenchmarkCase(
            "MAVLink application",
            "fragment decode",
            lambda: MavlinkApplicationCodec.decode_fragment(fragment),
            max(100, base_iterations // 5),
        ),
        BenchmarkCase(
            "MAVLink application",
            f"assemble {len(fragments)} fragments",
            assemble_packet,
            max(100, base_iterations // 40),
        ),
        BenchmarkCase(
            "MAVLink application",
            "serialize eight remote log records",
            log_batch.to_payload,
            max(100, base_iterations // 20),
        ),
        BenchmarkCase(
            "mission",
            "register and unregister",
            mission_registration_cycle,
            max(100, base_iterations // 20),
        ),
        BenchmarkCase(
            "mission",
            "complete mission lifecycle",
            mission_lifecycle_cycle,
            max(100, base_iterations // 100),
        ),
        BenchmarkCase(
            "mission",
            "manager snapshot with 100 registrations",
            engine.manager_snapshot,
            max(100, base_iterations // 20),
            engine.close,
        ),
    ] + _vehicle_cases(base_iterations)


async def _build_async_cases(base_iterations: int) -> tuple[
    list[AsyncBenchmarkCase],
    Callable[[], Awaitable[None]],
]:
    empty_bus = AsyncEventBus[int]()
    subscribed_bus = AsyncEventBus[int]()

    async def handler(_event: int) -> None:
        return None

    await subscribed_bus.subscribe(handler)

    container = DependencyContainer(auto_wire=False)

    async def singleton_factory() -> _TinyService:
        return _TinyService()

    async def transient_factory() -> _TinyService:
        return _TinyService()

    container.singleton("async-singleton", factory=singleton_factory)
    container.transient("async-transient", factory=transient_factory)
    await container.resolve_async("async-singleton")

    async def cleanup() -> None:
        await empty_bus.close()
        await subscribed_bus.close()
        await container.shutdown_async()

    return [
        AsyncBenchmarkCase(
            "events async",
            "publish without subscribers",
            lambda: empty_bus.publish(1),
            base_iterations,
        ),
        AsyncBenchmarkCase(
            "events async",
            "publish to one subscriber",
            lambda: subscribed_bus.publish(1),
            base_iterations,
        ),
        AsyncBenchmarkCase(
            "dependency async",
            "cached singleton resolve",
            lambda: container.resolve_async("async-singleton"),
            base_iterations,
        ),
        AsyncBenchmarkCase(
            "dependency async",
            "transient provider resolve",
            lambda: container.resolve_async("async-transient"),
            max(100, base_iterations // 2),
        ),
    ], cleanup


def _measure_memory(operation: Operation, iterations: int) -> tuple[float, int]:
    samples = min(iterations, 1_000)
    gc.collect()
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        for _ in range(samples):
            operation()
        after, _ = tracemalloc.get_traced_memory()
        retained = max(0, after - before) / samples

        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        operation()
        _current, peak = tracemalloc.get_traced_memory()
        peak_per_operation = max(0, peak - baseline)
        return retained, peak_per_operation
    finally:
        tracemalloc.stop()


async def _measure_async_memory(
    operation: AsyncOperation,
    iterations: int,
) -> tuple[float, int]:
    samples = min(iterations, 1_000)
    gc.collect()
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        for _ in range(samples):
            await operation()
        after, _ = tracemalloc.get_traced_memory()
        retained = max(0, after - before) / samples

        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        await operation()
        _current, peak = tracemalloc.get_traced_memory()
        return retained, max(0, peak - baseline)
    finally:
        tracemalloc.stop()


async def _measure_async_cases(
    base_iterations: int,
    repeats: int,
) -> list[tuple[AsyncBenchmarkCase, float, float, float, int]]:
    cases, cleanup = await _build_async_cases(base_iterations)
    measurements: list[
        tuple[AsyncBenchmarkCase, float, float, float, int]
    ] = []
    try:
        for case in cases:
            for _ in range(min(100, case.iterations)):
                await case.operation()
            wall_samples: list[float] = []
            cpu_samples: list[float] = []
            for _repeat in range(repeats):
                gc.collect()
                wall_start = time.perf_counter_ns()
                cpu_start = time.process_time_ns()
                for _ in range(case.iterations):
                    await case.operation()
                cpu_elapsed = time.process_time_ns() - cpu_start
                wall_elapsed = time.perf_counter_ns() - wall_start
                wall_samples.append(wall_elapsed / case.iterations)
                cpu_samples.append(cpu_elapsed / case.iterations)
            retained, peak = await _measure_async_memory(
                case.operation,
                case.iterations,
            )
            measurements.append(
                (
                    case,
                    statistics.median(wall_samples),
                    statistics.median(cpu_samples),
                    retained,
                    peak,
                )
            )
    finally:
        await cleanup()
    return measurements


def run_suite(
    base_iterations: int = 20_000,
    *,
    repeats: int = 5,
) -> list[BenchmarkResult]:
    """Run the suite and return machine-readable normalized measurements."""

    if base_iterations <= 0:
        raise ValueError("Benchmark iterations must be positive")
    if repeats <= 0:
        raise ValueError("Benchmark repeats must be positive")
    cases = build_cases(base_iterations)
    measurements: list[
        tuple[BenchmarkCase | AsyncBenchmarkCase, float, float, float, int]
    ] = []
    try:
        for case in cases:
            for _ in range(min(100, case.iterations)):
                case.operation()
            wall_samples: list[float] = []
            cpu_samples: list[float] = []
            for _repeat in range(repeats):
                gc.collect()
                wall_start = time.perf_counter_ns()
                cpu_start = time.process_time_ns()
                for _ in range(case.iterations):
                    case.operation()
                cpu_elapsed = time.process_time_ns() - cpu_start
                wall_elapsed = time.perf_counter_ns() - wall_start
                wall_samples.append(wall_elapsed / case.iterations)
                cpu_samples.append(cpu_elapsed / case.iterations)
            retained, peak = _measure_memory(case.operation, case.iterations)
            measurements.append(
                (
                    case,
                    statistics.median(wall_samples),
                    statistics.median(cpu_samples),
                    retained,
                    peak,
                )
            )
        measurements.extend(
            asyncio.run(_measure_async_cases(base_iterations, repeats))
        )
    finally:
        for case in reversed(cases):
            case.cleanup()

    noop = max(measurements[0][1], 1.0)
    results = [
        BenchmarkResult(
            category=case.category,
            name=case.name,
            iterations=case.iterations,
            wall_ns_per_op=wall,
            cpu_ns_per_op=cpu,
            relative_to_noop=wall / noop,
            retained_bytes_per_op=retained,
            peak_bytes_per_op=peak,
        )
        for case, wall, cpu, retained, peak in measurements
    ]
    category_order = {
        "baseline": 0,
        "abstracts": 1,
        "core models": 2,
        "events": 3,
        "events async": 4,
        "dependency": 5,
        "dependency async": 6,
        "MAVLink": 7,
        "MAVLink application": 8,
        "mission": 9,
    }
    return sorted(
        results,
        key=lambda result: category_order.get(result.category, 99),
    )


def _print_table(results: list[BenchmarkResult]) -> None:
    category_width = 12
    operation_width = 28

    def fit(value: str, width: int) -> str:
        if len(value) <= width:
            return value
        return f"{value[:width - 1]}…"

    print(
        f"{'Category':<{category_width}} {'Operation':<{operation_width}} "
        f"{'Wall ns':>10} {'CPU ns':>10} {'vs noop':>7} "
        f"{'Ret B':>8} {'Peak B':>8}"
    )
    print("-" * 89)
    for result in results:
        print(
            f"{fit(result.category, category_width):<{category_width}} "
            f"{fit(result.name, operation_width):<{operation_width}} "
            f"{result.wall_ns_per_op:>10.1f} {result.cpu_ns_per_op:>10.1f} "
            f"{result.relative_to_noop:>6.1f}x "
            f"{result.retained_bytes_per_op:>8.2f} "
            f"{result.peak_bytes_per_op:>8d}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20_000)
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Timed repetitions; the median is reported (default: 5)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use 2,000 base iterations for a fast health check",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()
    iterations = 2_000 if args.quick else args.iterations
    results = run_suite(iterations, repeats=args.repeats)
    if args.json:
        print(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "base_iterations": iterations,
                    "repeats": args.repeats,
                    "results": [asdict(result) for result in results],
                },
                indent=2,
            )
        )
    else:
        _print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
