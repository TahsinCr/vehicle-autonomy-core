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
from datetime import datetime, timezone
import gc
from importlib.metadata import PackageNotFoundError, version
import importlib.util
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import types
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from collections.abc import Awaitable, Callable


ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_PATH = ROOT / "benchmark-logs.json"
BENCHMARK_LOG_SCHEMA = 1


def _project_version() -> str:
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.partition("=")[2].strip().strip('"')
    try:
        return version("vehicle-autonomy-core")
    except PackageNotFoundError:
        return "unknown"


def _git_metadata() -> tuple[str, bool]:
    def run(*args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()

    try:
        changes = run("status", "--porcelain").splitlines()
        dirty = any(line[3:] != "benchmark-logs.json" for line in changes)
        return run("rev-parse", "HEAD"), dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", False


def _append_benchmark_log(path: Path, *, mode: str, result: object, status: str) -> None:
    """Append one reproducible run record with an atomic file replacement."""

    commit, dirty = _git_metadata()
    document: dict[str, object] = {"schema_version": BENCHMARK_LOG_SCHEMA, "runs": []}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded.get("schema_version") != BENCHMARK_LOG_SCHEMA:
            raise ValueError(f"Unsupported benchmark log schema in {path}")
        document = loaded
    runs = document.get("runs")
    if not isinstance(runs, list):
        raise ValueError(f"Invalid benchmark log structure in {path}")
    runs.append({
        "timestamp": datetime.now(timezone.utc).isoformat(), "version": _project_version(),
        "commit": commit, "dirty": dirty, "python": platform.python_version(),
        "platform": platform.platform(), "mode": mode, "status": status, "result": result,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as output:
        json.dump(document, output, indent=2)
        output.write("\n")
        temporary = Path(output.name)
    temporary.replace(path)


def _load_failures(result: "LoadBenchmarkResult") -> list[str]:
    failures: list[str] = []
    if result.writer_failed_records:
        failures.append(f"history writer lost {result.writer_failed_records} records")
    if result.thread_delta > 0:
        failures.append(f"load run leaked {result.thread_delta} thread(s)")
    return failures


def _load_standalone_checkout() -> None:
    """Expose a standalone checkout under its intended ``src.core`` name."""

    try:
        import src.core as loaded_core
    except ModuleNotFoundError:
        loaded_core = None
    if loaded_core is not None:
        loaded_path = Path(loaded_core.__file__).resolve().parent
        if loaded_path == ROOT:
            return
        for module_name in tuple(sys.modules):
            if module_name == "src.core" or module_name.startswith("src.core."):
                del sys.modules[module_name]
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
        raise RuntimeError("Could not load the core package") from None
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
    MessageHistory,
    MessageCache,
    SqliteMessageHistory,
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


@dataclass(frozen=True, slots=True)
class LoadBenchmarkResult:
    profile: str
    messages: int
    vehicles: int
    callbacks: int
    storage: str
    throughput_per_second: float
    latency_p50_ns: float
    latency_p95_ns: float
    latency_p99_ns: float
    cpu_ns_per_message: float
    retained_bytes_per_message: float
    peak_bytes_per_message: float
    writer_max_queued: int
    writer_failed_records: int
    thread_delta: int


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

    def to_dict(self) -> dict[str, int]:
        return {"type": 2, "autopilot": 3}


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

    def to_dict(self) -> dict[str, int]:
        return {"system": self.system, "type": self.type, "autopilot": self.autopilot}


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
        engine.run(mission)
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


_LOAD_PROFILES = {
    "normal": (2_000, 1, 2),
    "medium": (5_000, 5, 5),
    "heavy": (10_000, 10, 10),
    "stress": (20_000, 20, 20),
}


def _percentile(samples: list[int], percentile: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return float(ordered[index])


def run_load_profile(
    profile: str,
    *,
    storage: str = "sqlite",
) -> LoadBenchmarkResult:
    """Measure routing, registry, callbacks and recording as one hot path."""

    if profile not in _LOAD_PROFILES:
        raise ValueError(f"Unknown load profile: {profile}")
    if storage not in {"memory", "sqlite"}:
        raise ValueError("Load storage must be 'memory' or 'sqlite'")
    messages, vehicles, callbacks = _LOAD_PROFILES[profile]
    threads_before = threading.active_count()
    dialect = types.SimpleNamespace(MAV_AUTOPILOT_INVALID=8, MAV_TYPE_GCS=6)
    runtime = types.SimpleNamespace(connection=types.SimpleNamespace(mavlink=dialect))
    runtime._application_handlers = ApplicationHandlers(runtime)
    registry = VehicleRegistry(runtime, history_capacity=32)
    registry.running = True
    router = MavlinkMessageRouter(
        _RouterConnection(),  # type: ignore[arg-type]
        state_capacity=max(128, vehicles * 8),
        source_capacity=max(32, vehicles * 4),
    )
    temporary = tempfile.TemporaryDirectory(prefix="vehicle-core-benchmark-")
    history: MessageHistory
    if storage == "sqlite":
        history = SqliteMessageHistory(
            Path(temporary.name) / "telemetry.sqlite3",
            limit=messages,
            queue_capacity=messages,
            batch_size=128,
            wal=True,
        )
    else:
        history = MessageHistory(
            limit=messages,
            background=True,
            queue_capacity=messages,
            batch_size=128,
        )
    subscriptions = [
        router.envelopes.subscribe(registry.accept),
        router.envelopes.subscribe(history.append),
    ]
    delivered = 0

    def callback(_message: object) -> None:
        nonlocal delivered
        delivered += 1

    subscriptions.extend(
        router.subscribe(callback, "HEARTBEAT") for _ in range(callbacks)
    )
    latencies: list[int] = []
    max_queued = 0
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    tracemalloc.start()
    retained_before, _ = tracemalloc.get_traced_memory()
    try:
        for sequence in range(1, messages + 1):
            message = _VehicleMessage((sequence % vehicles) + 1)
            envelope = MavlinkMessageEnvelope.wrap(sequence, message)
            started = time.perf_counter_ns()
            router._dispatch(envelope)
            latencies.append(time.perf_counter_ns() - started)
            if sequence % 64 == 0 and history.writer_stats is not None:
                max_queued = max(max_queued, history.writer_stats.queued)
        history.flush(timeout=30.0)
        wall_elapsed = time.perf_counter_ns() - wall_start
        cpu_elapsed = time.process_time_ns() - cpu_start
        retained_after, peak = tracemalloc.get_traced_memory()
        stats = history.writer_stats
        if delivered != messages * callbacks:
            raise RuntimeError("Combined load callback delivery was incomplete")
        result = LoadBenchmarkResult(
            profile=profile,
            messages=messages,
            vehicles=vehicles,
            callbacks=callbacks,
            storage=storage,
            throughput_per_second=messages / (wall_elapsed / 1_000_000_000),
            latency_p50_ns=_percentile(latencies, 0.50),
            latency_p95_ns=_percentile(latencies, 0.95),
            latency_p99_ns=_percentile(latencies, 0.99),
            cpu_ns_per_message=cpu_elapsed / messages,
            retained_bytes_per_message=max(0, retained_after - retained_before) / messages,
            peak_bytes_per_message=max(0, peak - retained_before) / messages,
            writer_max_queued=max_queued,
            writer_failed_records=0 if stats is None else stats.failed_records,
            thread_delta=0,
        )
    finally:
        tracemalloc.stop()
        for subscription in subscriptions:
            subscription.cancel()
        history.close()
        registry.close()
        router.messages.close()
        router.envelopes.close()
        router.errors.close()
        temporary.cleanup()
    return replace(
        result,
        thread_delta=max(0, threading.active_count() - threads_before),
    )


def run_load_profiles(
    profile: str,
    *,
    storage: str = "sqlite",
    repeats: int = 1,
) -> LoadBenchmarkResult:
    """Run a load profile repeatedly and report representative median costs."""

    if repeats < 1:
        raise ValueError("Load repetitions must be positive")
    results = [run_load_profile(profile, storage=storage) for _ in range(repeats)]
    return _summarize_load_results(results)


def _summarize_load_results(
    results: list[LoadBenchmarkResult],
) -> LoadBenchmarkResult:
    """Combine compatible load runs without hiding acceptance failures."""

    if not results:
        raise ValueError("At least one load result is required")
    identity = (
        results[0].profile,
        results[0].messages,
        results[0].vehicles,
        results[0].callbacks,
        results[0].storage,
    )
    if any(
        (result.profile, result.messages, result.vehicles, result.callbacks, result.storage)
        != identity
        for result in results[1:]
    ):
        raise ValueError("Load results must describe the same profile")
    representative = results[len(results) // 2]

    def median(field: str) -> float:
        return float(statistics.median(getattr(result, field) for result in results))

    return replace(
        representative,
        throughput_per_second=median("throughput_per_second"),
        latency_p50_ns=median("latency_p50_ns"),
        latency_p95_ns=median("latency_p95_ns"),
        latency_p99_ns=median("latency_p99_ns"),
        cpu_ns_per_message=median("cpu_ns_per_message"),
        retained_bytes_per_message=median("retained_bytes_per_message"),
        peak_bytes_per_message=median("peak_bytes_per_message"),
        writer_max_queued=max(result.writer_max_queued for result in results),
        writer_failed_records=sum(result.writer_failed_records for result in results),
        thread_delta=max(result.thread_delta for result in results),
    )


def _regressions(
    results: list[BenchmarkResult],
    baseline_path: Path,
    maximum_percent: float,
) -> list[str]:
    """Return operation-specific regressions after suite-wide calibration."""

    document = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = {
        (item["category"], item["name"]): (
            float(item["wall_ns_per_op"]),
            float(item["cpu_ns_per_op"]),
        )
        for item in document["results"]
    }
    current_operations = [result for result in results if result.category != "baseline"]
    baseline_operations = {
        key for key in baseline if key[0] != "baseline"
    }
    matched = [
        (result, baseline[(result.category, result.name)])
        for result in current_operations
        if result.category != "baseline"
        and (result.category, result.name) in baseline
    ]
    if not matched:
        raise ValueError("Benchmark baseline has no matching operations")
    expected_matches = max(len(current_operations), len(baseline_operations))
    if len(matched) / expected_matches < 0.8:
        raise ValueError(
            "Benchmark baseline matches fewer than 80% of operations "
            f"({len(matched)}/{expected_matches})"
        )
    current_anchor = next(
        (result for result in results if result.category == "baseline"), None
    )
    baseline_anchor = next(
        (value for key, value in baseline.items() if key[0] == "baseline"), None
    )
    if current_anchor is None or baseline_anchor is None:
        raise ValueError("Benchmark comparison requires a baseline calibration operation")
    calibration = current_anchor.wall_ns_per_op / baseline_anchor[0]
    cpu_calibration = current_anchor.cpu_ns_per_op / baseline_anchor[1]
    failures: list[str] = []
    factor = 1.0 + maximum_percent / 100.0
    for result, previous in matched:
        wall_ratio = (result.wall_ns_per_op / previous[0]) / calibration
        cpu_ratio = (result.cpu_ns_per_op / previous[1]) / cpu_calibration
        # A real code-path regression normally appears in both clocks. Requiring
        # both prevents scheduler and CPU-frequency noise from failing CI.
        normalized_ratio = min(wall_ratio, cpu_ratio)
        if normalized_ratio > factor:
            change = (normalized_ratio - 1.0) * 100.0
            failures.append(f"{result.category}/{result.name}: +{change:.1f}%")
    return failures


def _load_regressions(
    result: LoadBenchmarkResult,
    baseline_path: Path,
    maximum_percent: float,
) -> list[str]:
    """Compare portable combined-load costs with a previous same-host run."""

    previous = json.loads(baseline_path.read_text(encoding="utf-8"))
    identity_fields = ("profile", "messages", "vehicles", "callbacks", "storage")
    mismatches = [
        field
        for field in identity_fields
        if previous.get(field) != getattr(result, field)
    ]
    if mismatches:
        raise ValueError(
            "Load baseline does not match the current profile: "
            + ", ".join(mismatches)
        )
    factor = 1.0 + maximum_percent / 100.0
    ratios = {
        "throughput": float(previous["throughput_per_second"])
        / result.throughput_per_second,
        "latency p99": result.latency_p99_ns / float(previous["latency_p99_ns"]),
        "CPU per message": result.cpu_ns_per_message
        / float(previous["cpu_ns_per_message"]),
    }
    corroborated_latency = (
        ratios["latency p99"] > factor
        and max(ratios["throughput"], ratios["CPU per message"]) > factor
    )
    return [
        f"{name}: +{(ratio - 1.0) * 100.0:.1f}%"
        for name, ratio in ratios.items()
        if ratio > factor and (name != "latency p99" or corroborated_latency)
    ]


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
    parser.add_argument(
        "--load-profile",
        choices=tuple(_LOAD_PROFILES),
        help="Run one combined router/vehicle/callback/history load profile",
    )
    parser.add_argument(
        "--load-storage",
        choices=("memory", "sqlite"),
        default="sqlite",
    )
    parser.add_argument(
        "--load-repeats",
        type=int,
        default=1,
        help="Load-profile repetitions; median costs are reported (default: 1)",
    )
    parser.add_argument(
        "--compare-load",
        type=Path,
        help="Compare a combined load run with a previous same-host JSON result",
    )
    parser.add_argument(
        "--aggregate-load",
        type=Path,
        nargs="+",
        help="Combine load-result JSON files and print their median costs",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        help="Fail on operation-specific regression after suite-wide calibration",
    )
    parser.add_argument(
        "--max-regression-percent",
        type=float,
        default=35.0,
        help="Allowed calibrated regression when --compare is used (default: 35)",
    )
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--no-log", action="store_true", help="Do not append benchmark history")
    args = parser.parse_args()
    if args.max_regression_percent < 0:
        parser.error("--max-regression-percent must be non-negative")
    if args.load_repeats < 1:
        parser.error("--load-repeats must be positive")
    if args.aggregate_load is not None:
        if args.load_profile is not None:
            parser.error("--aggregate-load cannot be combined with --load-profile")
        results = [
            LoadBenchmarkResult(**json.loads(path.read_text(encoding="utf-8")))
            for path in args.aggregate_load
        ]
        print(json.dumps(asdict(_summarize_load_results(results)), indent=2))
        return 0
    if args.load_profile is not None:
        result = run_load_profiles(
            args.load_profile,
            storage=args.load_storage,
            repeats=args.load_repeats,
        )
        failures = _load_failures(result)
        if args.compare_load is not None:
            failures.extend(
                _load_regressions(
                    result,
                    args.compare_load,
                    args.max_regression_percent,
                )
            )
        if args.json:
            print(json.dumps(asdict(result), indent=2))
        else:
            print(f"Combined load profile: {result.profile} ({result.storage})")
            print(
                f"{result.messages:,} messages, {result.vehicles} vehicles, "
                f"{result.callbacks} callbacks"
            )
            print(f"Throughput: {result.throughput_per_second:,.1f} messages/s")
            print(
                "Latency p50/p95/p99: "
                f"{result.latency_p50_ns / 1_000:.1f}/"
                f"{result.latency_p95_ns / 1_000:.1f}/"
                f"{result.latency_p99_ns / 1_000:.1f} us"
            )
            print(f"CPU: {result.cpu_ns_per_message / 1_000:.1f} us/message")
            print(
                "Memory retained/peak: "
                f"{result.retained_bytes_per_message:.1f}/"
                f"{result.peak_bytes_per_message:.1f} bytes/message"
            )
            print(
                f"Writer max queued: {result.writer_max_queued}; "
                f"failed records: {result.writer_failed_records}; "
                f"thread delta: {result.thread_delta}"
            )
        status = "failed" if failures else "passed"
        if not args.no_log:
            _append_benchmark_log(args.log_file, mode=f"load:{args.load_profile}:{args.load_storage}", result=asdict(result), status=status)
        for failure in failures:
            print(f"Load acceptance failure: {failure}", file=sys.stderr)
        return 1 if failures else 0
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
    regressions: list[str] = []
    if args.compare is not None:
        regressions = _regressions(
            results,
            args.compare,
            args.max_regression_percent,
        )
        if regressions:
            print("Performance regressions:", file=sys.stderr)
            for regression in regressions:
                print(f"- {regression}", file=sys.stderr)
        else:
            print("Benchmark regression check passed", file=sys.stderr)
    status = "failed" if regressions else "passed"
    if not args.no_log:
        _append_benchmark_log(args.log_file, mode="quick" if args.quick else "suite", result={"base_iterations": iterations, "repeats": args.repeats, "results": [asdict(result) for result in results], "regressions": regressions}, status=status)
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
