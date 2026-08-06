# Changelog

All notable changes to this project are documented in this file.

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
  `Kirlangic-Team/vehicle-autonomy-core` as the repository location.
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

[v1.1]: https://github.com/Kirlangic-Team/vehicle-autonomy-core/compare/v1.0...v1.1
[v1.0]: https://github.com/Kirlangic-Team/vehicle-autonomy-core/releases/tag/v1.0
