# Changelog

All notable changes to this project are documented in this file.

## [v1.2] - 2026-08-13

### Added

- Added dependency-free Python 3.10 fallbacks for string enums and grouped
  cleanup errors.
- Added deterministic concurrency tests for mission callback ownership,
  paused execution timeouts, scoped dependency resolution and asynchronous
  event waits.
- Added configurable in-flight assembly, byte and recently completed packet
  limits to the MAVLink application assembler.

### Changed

- Lowered the supported Python version to 3.10 and verified the source tree,
  standard test discovery and installed wheel on Python 3.10.18.
- Mission lifecycle callbacks for one mission are now serialized. Stop waits
  for an active `start()` or `tick()` call before invoking mission cleanup, and
  pause prevents another tick from starting while the pause callback runs.
- Mission transition events are published outside the engine condition lock
  while preserving transition order. Reentrant subscribers can safely issue
  lifecycle commands.
- Mission execution timeouts now count active running time and exclude time
  spent paused.
- Scoped dependencies now coordinate concurrent synchronous and asynchronous
  resolution within each scope.
- Python bytecode and cache directories are excluded from built wheels.
- The MAVLink asyncio bridge now bounds messages before they reach the event
  loop as well as in its asyncio queue, with at most one pending drain callback.
- Updated package metadata to version `1.2.0`.

### Fixed

- Marked mission chains failed when their factory, registration or next launch
  step raises, preventing inactive chains from remaining active indefinitely.
- Kept async-only resources attached when synchronous dependency shutdown is
  rejected, allowing cleanup to be retried with `shutdown_async()`.
- Prevented a shared dependency instance from being closed while another token
  in the same container still references it.
- Closed the subscription race in `AsyncEventBus.wait_for()` and the immediate
  delivery leak in `MavlinkRuntime.once()`.

## [v1.1.1] - 2026-08-12

### Added

- Added `tests/run.py` as a straightforward entry point for running the entire
  test suite. It can be called from the repository root and returns a failing
  exit code when any test fails.

### Changed

- Replaced the hard-to-follow `test_imports.py` helper with
  `test_package_layout.py`. The same compatibility guarantees are retained,
  but the test now builds real temporary package layouts and imports them in a
  clean Python process.
- Gave package layout, project metadata and repository naming checks clearer
  boundaries so failures are easier to understand.
- Updated the English and Turkish guides with the recommended test command and
  a concise explanation of what the package-layout checks protect.
- Updated package metadata to version `1.1.1`.

## [v1.1] - 2026-08-06

### Added

- Added `MissionLifecycle` as a ready-to-use component for pause, resume, stop,
  cancel, completion, failure, progress, checkpoints and mission transitions.
- Added `MissionScheduler` as a ready-to-use component for launch, parallel
  execution, queues, resource conflicts, prerequisites, retries and mission
  chains.
- Added `lifecycle=` and `scheduler=` options to `MissionEngine`, allowing an
  application to pass focused subclasses without replacing the complete engine.
- Added tests for default component binding, custom lifecycle and scheduler
  subclasses, ownership rules and package-level exports.

### Changed

- Replaced the mission engine's lifecycle and scheduling mixin inheritance with
  explicit composition. `MissionEngine` now inherits only from `Service` and
  exposes its active components through `engine.lifecycle` and
  `engine.scheduler`.
- Kept the existing `MissionEngine` facade intact. Calls such as `launch()`,
  `run_parallel()`, `pause()`, `complete()` and `wait()` now delegate to the
  corresponding component.
- Renamed `mission/scheduling.py` to `mission/scheduler.py` so the module name
  matches the concrete `MissionScheduler` class it provides.
- Exported `MissionLifecycle` and `MissionScheduler` from both `src.core` and
  `src.core.mission`.
- Updated the English and Turkish mission documentation with the component
  boundary, default setup and a small customization example.
- Updated package metadata to version `1.1.0`.

## [v1.0] - 2026-08-06

### Added

- Added `Model` and `Service` as the small common contracts for public data
  models and lifecycle-aware services.
- Added a dependency injection container with transient, singleton and scoped
  lifetimes, class and factory providers, ready instances, autowiring and child
  scopes.
- Added explicit parameter injection with `Inject`, function and constructor
  decorators, synchronous and asynchronous resolution, ordered warmup and
  circular-dependency reporting.
- Added deterministic dependency cleanup for `close()` and `aclose()` resources,
  including context-manager shutdown, token replacement, unregister and
  aggregate cleanup failures.
- Added thread-safe `EventBus` and asyncio-native `AsyncEventBus`
  implementations with typed filters, predicates, one-shot and limited
  subscriptions, replay, blocking or async waits and cancellable periodic
  publishing.
- Added optional bounded event history, latest/query helpers, delivery
  statistics, sequential or concurrent async delivery and configurable error
  policies.
- Added reusable before, after, subscriber-error and wait-timeout actions for
  synchronous and asynchronous event buses.
- Added `EventEngine` and `AsyncEventEngine` for lazily created named channels
  with shared defaults and one aggregate lifecycle.
- Added a class-based `Mission` contract with unique numeric instance IDs,
  class-derived default names and per-instance name overrides.
- Added `MissionEngine` with registration, snapshots, transitions, progress,
  checkpoints, event history, pause, resume, stop, cancel, completion and
  retryable failure handling.
- Added concurrent mission execution with resource and class conflicts,
  priority-based authority, reject/queue/preempt policies, prerequisite
  policies, execution timeouts and queue timeouts.
- Added tag- and resource-based mission intervention so a mission can affect
  authorized work without directly knowing every other mission instance.
- Added sequential `MissionChain` execution using `Mission` subclasses and an
  optional application-owned mission factory.
- Added validated serial, UDP and TCP `MavlinkEndpoint` configuration and a
  thread-safe `pymavlink` connection wrapper.
- Added `MavlinkMessageRouter` as the single reader for a physical connection,
  with metadata filters, subscriptions, blocking waits, bounded history,
  latest-message lookup, per-type cache and delivery statistics.
- Added `MavlinkMessageEnvelope`, structural MAVLink message protocols and a
  reusable bounded `MessageCache`.
- Added `MavlinkAsyncChannel` as a bounded bridge from the router thread to one
  asyncio event loop, including observable overflow counts and clean restart
  sessions.
- Added a JSON application protocol over MAVLink `V2_EXTENSION` with packet
  validation, fragmentation, out-of-order reassembly, CRC32 checks, duplicate
  handling, source isolation and fragment expiry.
- Added `MavlinkApplicationPeer` with transport state, heartbeat and ping/pong
  liveness, round-trip measurement and packet-ID-correlated request/response.
- Added a bounded `MavlinkApplicationDispatcher` and handler registry so
  application work runs outside the MAVLink receive thread and requests receive
  correlated acknowledgements or errors.
- Added `MavlinkRuntime` as the high-level owner of the client, router,
  application channel, peer and dispatcher lifecycles.
- Added size-limited, JSON-compatible remote-log records and ordered batches
  without UI-specific severity values or a storage backend.
- Added Python 3.11 project metadata, editable installation and optional
  `pymavlink` dependency metadata.
- Added English and Turkish documentation covering the core boundary,
  `src/core` integration, every package, lifecycle rules and working usage
  examples.
- Added hardware-free unit tests organized by dependency, events, mission and
  MAVLink concerns, plus standalone and alternative-parent package import
  checks.

### Changed

- Established `Vehicle Autonomy Core` as the project name and
  `TahsinCr/vehicle-autonomy-core` as the repository location.
- Made `src.core` the intended consumer import boundary while keeping all
  internal imports relative, allowing the package to work below another parent
  package as well.
- Organized the dependency, event and mission implementations into focused
  packages while preserving their public package-level exports.
- Kept mission behavior class-based: applications implement concrete `Mission`
  subclasses while the core owns only scheduling, lifecycle and observation.
- Kept MAVLink responsibilities layered: connection owns transport, router owns
  reads, application channel owns framing, peer owns correlation, dispatcher
  owns handler execution and runtime composes their lifecycles.
- Defined callback and worker ownership explicitly. Router subscribers run on
  the receive thread; async channel delivery belongs to one event loop; mission
  and dispatcher work runs in dedicated worker threads.
- Kept `pymavlink` outside the base dependency set so non-MAVLink parts of the
  core can be installed and tested independently.
- Kept remote-log levels transport-oriented and left UI presentation mappings
  to the consuming application.

### Fixed

- Ensured dependency contexts are restored even when synchronous or
  asynchronous shutdown fails.
- Ensured replaced and unregistered singleton or scoped resources are disposed
  exactly once and async-only disposal is requested explicitly.
- Ensured dependency shutdown attempts every cached resource in reverse
  creation order without losing individual failures.
- Prevented router and application-peer shutdown from discarding references to
  threads that are still alive or closing a connection beneath active receive
  work.
- Ensured pending peer requests are awakened during shutdown and stopped peer
  monitors cannot continue publishing state or packets.
- Handled event-loop closure races while forwarding MAVLink messages into an
  asyncio queue and cleared stale queued messages between channel sessions.
- Prevented the application dispatcher from accepting new work after stop,
  leaking queue capacity or sending a late response from an old generation.
- Detached caller-owned payload dictionaries in application, dispatch,
  mission-snapshot and remote-log models.
- Strengthened application packet validation for timestamps, source IDs, packet
  type length, JSON compatibility, non-finite numbers, protocol version,
  fragment consistency, CRC and maximum encoded size.
- Corrected project naming and repository links so the legacy misspelling is no
  longer present in source, metadata or documentation.

[v1.2]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.1.1...v1.2
[v1.1.1]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.1...v1.1.1
[v1.1]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.0...v1.1
[v1.0]: https://github.com/TahsinCr/vehicle-autonomy-core/releases/tag/v1.0
