**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/operations.md)

# Operations, testing and performance

## Shutdown checklist

Prefer structured ownership:

```python
with DependencyContainer() as dependencies:
    with MessageHistory(background=True) as history:
        with MavlinkRuntime(endpoint) as link:
            link.add_history(history)
            ...
```

For async resources use `async with` and `shutdown_async()`. Never call sync
shutdown when a container owns async-only cleanup. If cleanup raises, retain the
owner and retry after correcting the underlying failure.

Mission cleanup failure is intentionally not converted into mission completion.
A mission stays `STOPPING` and keeps resource ownership until `stop()` succeeds.

## Capacity planning

| Area | Limit | Overflow behavior |
|---|---|---|
| Event periodic schedules | `max_schedules` | registration error |
| Replay pending events | `replay_buffer_limit` | affected subscription cancelled and reported |
| Runtime telemetry callbacks | `callback_capacity` / `delivery_capacity` | oldest telemetry callback dropped and counted |
| Runtime lifecycle actions | `callback_action_capacity` / `action_capacity` | fatal delivery error |
| Application dispatcher | `max_pending` | dispatch rejected |
| History writer | `queue_capacity` | explicit recording failure |
| Router latest state | `state_capacity` | LRU eviction |
| Router source condition maps | `source_capacity` | LRU source eviction |
| Vehicle state | `vehicle_state_retention` | disconnected state removed after interval |
| Cache | `per_key_limit`, `max_keys` | oldest item/key evicted |

Do not select capacities solely from message frequency. Include the longest
expected callback/storage stall and a safety margin.

## Observability

- `EventBus.stats`: published, delivered, failed.
- `MavlinkRuntime.state`: lifecycle, connection, peer and router state.
- `MavlinkMessageRouter.stats`: receive/filter/dispatch/loss/state counters.
- `MavlinkRuntime.dropped_callbacks`: callback backpressure.
- `MavlinkRuntime.delivery_error`: fatal callback delivery error.
- `MessageCache.stats`: keys, retained messages, evicted keys.
- `MessageHistory.writer_stats`: submitted, processed, persisted, failed-record,
  queued and batch counters plus the failure flag.
- `MessageHistory.recording_error`: original writer exception.
- `MavlinkApplicationPeer.state`: liveness, RTT and packet counters.
- `MissionEngine.manager_snapshot()`: active/queued/paused missions and resource owners.
- `MissionEngine.query_events()`: structured retained mission events.

Read snapshot properties freely; avoid polling at unnecessarily high frequency.

## SQLite guidance

Use bounded retention for embedded storage unless complete archival is required.
`wal=True` improves writer/read coexistence but creates WAL sidecar files and is
therefore opt-in. `busy_timeout` controls how long SQLite waits for a lock.
Batch size and flush interval trade latency for transaction efficiency.

Always inspect `recording_error` or runtime history errors. A successful MAVLink
receive does not imply a successful persistent write.

## Test commands

Run the complete suite:

```bash
python run_tests.py
```

Equivalent standard discovery:

```bash
python -m unittest discover -v
```

Verify syntax/import compilation:

```bash
python -m compileall -q .
```

Install and run the development quality gates against the supported Python 3.10
type target:

```bash
python3.10 -m pip install -e ".[quality]"
python run_quality.py
python run_quality.py --tests
python run_quality.py --coverage
python run_stress_tests.py --repeats 25
```

`run_quality.py` requires an exact Python 3.10 interpreter, using `python3.10`
by default and discovering an installed pyenv Python 3.10 when that shim is not
active. Pass `--python /path/to/python3.10` when the executable has a different
name. Its default path runs Ruff, Pyright against that interpreter,
source compilation and the public API contract. `--tests` adds the full suite;
`--coverage` runs that suite through the configured branch-coverage gate.

Coverage includes branch decisions and enforces an 82% project baseline.
Pyright checks definite name and control-flow failures, unused production
symbols and invalid return contracts. The distributed `py.typed` marker lets
downstream type checkers consume the same annotations. The stress runner repeats
selected concurrency regressions with a fresh suite on every pass.

The CI matrix runs supported Python versions and builds the wheel. Native ARM64
also installs optional `pymavlink`, so the real UDP loopback contract runs on
both architectures. Tests cover standalone checkout loading and the intended
`src/core` submodule layout.

CI also compares the callable contract with the highest stable semantic-version
tag reachable from the previous commit. Existing exports, signatures, public
enum names/values and property accessors must remain intact on a patch line,
while additive APIs are allowed. Minor versions may intentionally establish a
new contract. Workflow Actions are pinned to immutable commit SHAs; their
version comments remain available to Dependabot and reviewers.
`pip-audit` checks the optional MAVLink dependency set in an isolated job,
Dependabot checks Python and GitHub Actions dependencies weekly, and CodeQL runs
extended Python security queries on changes and on a weekly schedule.

Run the same dependency audit locally with:

```bash
python -m pip install -e ".[mavlink,security]"
pip-audit --local --skip-editable
```

## Benchmarks

```bash
python run_benchmarks.py
python run_benchmarks.py --quick --json > benchmark.json
python run_benchmarks.py --quick --compare benchmark.json
python run_benchmarks.py --load-profile normal --load-storage sqlite
```

The benchmark reports wall time, CPU time, retained bytes per operation and peak
temporary allocation. It covers core model serialization, sync/async events,
dependency resolution, MAVLink filtering/cache/routing/application packets and
mission operations.

Benchmark values are comparative, not hard real-time guarantees. Compare the
same interpreter, CPU governor and load. Prefer ratios and distribution trends
over a fixed microsecond threshold from another machine.

`--compare` matches stable operation names, calibrates against the dedicated
no-op anchor and rejects an operation-specific cost increase over 35% unless
`--max-regression-percent` changes that budget. At least 80% of operations must
match the reference so missing coverage cannot silently weaken the comparison. A regression must appear in
both wall and CPU time, which filters out
runner scheduling noise without accepting a consistent code-path slowdown.
CI uses the same calibrated 35% budget. Every run is appended atomically to
`benchmark-logs.json` with UTC time, package version, commit, dirty-tree state,
platform and result data. Use `--no-log` only for disposable probes. Combined
load runs fail when SQLite loses records or leaves worker threads behind.
`--compare-load previous-load.json` also checks throughput, p99 latency and CPU
cost per message against a same-host run. Throughput and CPU are independent
gates; p99 fails only when an aggregate cost also regresses, preventing one
short scheduling spike from rejecting an otherwise stable run.
CI compares both the immediately preceding commit and, when different, the
highest reachable stable prior release tag. This catches local regressions as well as smaller
slowdowns accumulated across a release. Load-result comparison also requires
matching profile, storage and topology metadata. CI microbenchmarks use longer
nine-sample medians than the interactive `--quick` health check.

## Compatibility and versioning

Patch releases (`1.x.y`) preserve the published API and contain compatible
fixes, performance work and documentation updates. Minor releases (`1.x.0`)
may deliberately refine the public API; each such change is listed in the
changelog without keeping obsolete compatibility aliases. A new major version
is reserved for a foundational redesign of the core contracts.

Sign a release tag only after verifying its release commit:

```bash
git tag -s v1.8.2 -m "Vehicle Autonomy Core v1.8.2"
git tag -v v1.8.2
git push origin v1.8.2
```

With `gpg.format=ssh`, Git uses the configured SSH signing key; otherwise it
uses the configured GPG key. Never move a published release tag—publish a new
patch version instead.
Combined profiles (`normal`, `medium`, `heavy`, `stress`) exercise routing, multi-vehicle state,
multiple callbacks and background memory/SQLite recording together. They report
throughput, p50/p95/p99 latency, CPU and memory per message, writer pressure,
failed records and thread growth.

Production deployments should explicitly set finite `state_capacity` and
`source_capacity` values after measuring expected source cardinality. The
library keeps `None` as the general-purpose default because silently evicting
valid state is not universally safer. Likewise, dispatcher `workers=1` remains
the ordered default; increase it only for independent, thread-safe handlers.

## Hardware and integration validation

Before flight or field deployment, add application-owned tests for:

- real serial/UDP reconnect and malformed traffic;
- multiple simultaneous vehicle system IDs;
- sustained expected telemetry rate plus burst margin;
- storage-full and slow-storage behavior;
- callback and mission cleanup failures;
- process shutdown while requests are pending;
- SITL/HIL mission transitions and actuator safety behavior;
- multi-hour soak runs with memory/state counter monitoring.

The core unit suite verifies software contracts; it cannot replace vehicle,
transport and operating-system validation.
