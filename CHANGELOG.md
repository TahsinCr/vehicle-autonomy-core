# Changelog

All notable changes to this project are documented in this file.

## [v1.7.2] - 2026-09-12

### Added

- Added Ruff correctness checks, a gradual Pyright baseline, branch coverage
  enforcement and repeatable concurrency stress checks.
- Added combined MAVLink router, vehicle registry, callback and history load
  profiles plus same-machine JSON benchmark regression comparison.
- Added dedicated CI jobs for quality gates, concurrency stress, performance
  regression and native ARM64 execution.

### Changed

- Invalid provider return annotations now produce a focused dependency
  registration error instead of silently disabling token inference.
- A failed container-wide cleanup now places the container in an explicit
  cleanup-pending state; normal use stays blocked until shutdown is retried.

### Fixed

- Reserve dependency tokens for the complete unregister/disposal operation,
  prevent registrations from committing after shutdown starts and make
  concurrent async cleanup callers observe one cancellation-safe result.
- Stop child scopes from resolving through a parent whose shutdown has begun.
- Preserve mission success/failure intent for external lifecycle calls and
  uncaught worker errors until cleanup and the terminal transition both commit.
  Competing stop/cancel commands can no longer replace that pending outcome.

### Documentation

- Documented the quality commands, stress runner, benchmark baselines, combined
  SQLite load profiles and production capacity recommendations in both languages.

## [v1.7.1] - 2026-09-12

### Added

- Added visible mission cleanup fault state and `retry_cleanup()` so a pending
  success result or retryable failure survives cleanup recovery.
- Added terminal dependency-container state and explicit errors for use after
  shutdown or token reuse while resource cleanup is pending.
- Added separate processed, persisted and failed-record history writer metrics,
  plus last-observed timestamps for vehicle and component state.

### Changed

- Successful dependency-container shutdown is terminal across every lifetime;
  concurrent synchronous callers now wait for the same cleanup result.
- A permanently failed MAVLink history is reported once and detached from live
  traffic, while storage ownership remains with the caller.
- MAVLink message-rate requests now reject booleans and invalid target IDs
  instead of coercing them to integers.

### Fixed

- Preserve callback-driven mission phase, result, reason and retryability until
  cleanup succeeds instead of losing the terminal intent in `STOPPING`.
- Prevent a failed dependency unregister from freeing its token while the old
  resource is still alive.
- Keep background message histories closed after a stopped writer reports its
  stored failure, and keep blocking async MAVLink I/O owned across repeated
  task cancellation.
- Prune non-heartbeat MAVLink components by their last observed traffic time.
- Retain timed-out synchronous event schedule threads so a later `close()` can
  finish joining them.

### Documentation

- Added parallel English and Turkish Markdown documentation covering
  architecture, setup, core abstractions, dependency injection, sync/async
  events, mission orchestration, MAVLink, the application protocol and
  operations.
- Added public API indexes, page-level GitHub language switching and links from
  the corresponding English and Turkish README files.

## [v1.7] - 2026-09-11

### Added

- Added `MissionCleanupError` for incomplete mission resource cleanup.
- Added optional background serialization for in-memory `MessageHistory` and
  optional bounded callback concurrency for `AsyncMavlinkRuntime`.
- Added an optional `max_keys` limit to the generic `MessageCache`.
- Added bounded router state, disconnected vehicle-state retention and explicit
  pruning controls for long-running, multi-vehicle runtimes.
- Added lightweight cache/router/history writer statistics, optional SQLite WAL
  mode and a configurable SQLite busy timeout.
- Added a bounded synchronous event shutdown timeout with an explicit
  `EventShutdownTimeoutError`.

### Changed

- Native MAVLink `condition=` filters are now limited to live subscriptions.
  Historical `latest()`, `history()` and `wait_for()` calls require a Python
  predicate instead of evaluating old messages against current source state.
- Model serialization represents frozen sets as tuple/list values so nested
  frozen models remain serializable and JSON conversion stays predictable.
- Invalid boolean values are rejected consistently for integer MAVLink IDs,
  endpoint fields, application channel settings and DI priorities.

### Fixed

- Keep missions in `STOPPING` with resource ownership intact when cleanup
  fails. Cleanup can be retried, and a swallowed callback-exit sentinel can no
  longer strand a mission before terminal finalization.
- Detect cached dependency cycles across independent asyncio tasks, not only
  execution threads. Failed and dynamically awaitable disposal stays tracked
  until a later synchronous or asynchronous retry succeeds.
- Claim dependency resources before disposal so concurrent unregister and
  shutdown paths cannot close the same instance twice.
- Route vehicle and component async transport calls through the runtime-owned
  cancellation-safe I/O path instead of leaving executor work detached.
- Give async MAVLink delivery one fatal-state transition that wakes registry
  waiters, rejects later work and reports the original failure.
- Isolate replay-buffer overflow to the affected sync or async event subscriber
  and join synchronous periodic publisher threads during bus shutdown.
- Reject checkpoint updates after mission termination and protect the reserved
  checkpoint event name from user field replacement.
- Schedule mission retries and scheduler wake notifications without wall-clock
  jumps or lost wake-up windows.
- Correlate peer liveness probes with the expected source system and component.
- Avoid sorting every router `latest()` query and remove per-message route-map
  merging from the dispatch hot path.

## [v1.6] - 2026-09-08

### Added

- Added source-local MAVLink condition state, wall-clock packet receive times,
  configurable SQLite history batching and an explicit `CallbackTimeoutError`.
- Added cancellable router ingress filters through `add_filter()`. Filters
  compose in registration order and support direct and decorator registration.

### Changed

- Parallel-stage `MissionExecutionResult.mission_id` is now `None`; a parallel
  result belongs to its named group rather than whichever child happened to
  finish last.
- Cancelling an async MAVLink transport call now keeps ownership of its worker
  until the blocking operation returns instead of leaving detached executor work.

### Fixed

- Unwind mission callbacks immediately after callback-driven `complete()` or
  `fail()`, and defer terminal publication and resource release until user code
  has stopped. Completion now claims `STOPPING` atomically, preventing concurrent
  pause/stop transitions from corrupting the final phase.
- Require a controlling mission to be running. Registered, paused and terminal
  missions can no longer use retained controllers to affect other missions.
- Revalidate prerequisites, capacity and conflict policy immediately before a
  mission enters `STARTING`, removing nondeterministic launch/queue races.
- Guard background activation with its owner's current state and ignore failure
  propagation when a `KEEP_RUNNING` background's mission owner was removed.
- Detect dependency initialization cycles spanning multiple threads. Replacement
  disposal no longer executes user `close()` code while holding the registration
  lock, and token detachment is atomic with registry updates.
- Evaluate native MAVLink conditions against the current system/component state
  instead of the connection-wide last-message dictionary.
- Move SQLite JSON serialization onto its writer thread, insert records in
  batches and trim retention once per transaction rather than once per message.
- Make replay overflow explicit instead of silently discarding live events, and
  evaluate replay predicates outside event-bus locks in sync and async buses.
- Give sync and async callback timeouts the same admission-to-callback budget;
  user-raised `TimeoutError` is no longer mistaken for a framework timeout.
- Persist the receive wall-clock timestamp captured with each MAVLink envelope
  instead of taking a delayed timestamp inside history subscribers.
- Normalize MAVLink `NaN` and positive/negative infinity to JSON `null` in
  memory and SQLite history snapshots without changing live message objects.

## [v1.5] - 2026-09-08

### Added

- Added per-registration callback policies and hooks: `frequency_hz`,
  `max_calls`, `once`, `timeout`, `predicate`, `enabled`, before/success/error/
  timeout/after hooks and enable/disable controls. MAVLink message subscriptions
  and lifecycle actions return callable `CallbackSubscription` decorator handles.
- Move high-level synchronous receive callbacks, predicates and hooks onto one
  bounded runtime worker. Expose dropped delivery counts and report shutdown
  timeout for callbacks that do not return. Add policy/hook benchmarks and
  deterministic slow-consumer, overflow, rate-limit and async timeout tests.
- Added optional `MessageHistory` and derived `SqliteMessageHistory` storage,
  attached at runtime through `add_history()`. Both support total retention
  limits or unlimited recording, source/type/time queries, snapshots and clear.
  SQLite stores portable JSON and reopens recordings without a live connection.
  Storage remains caller-owned; registration cancellation and runtime close
  detach it. Recording errors are surfaced through runtime errors.
- Added `vehicles.get_component(id)` to retrieve matching components across
  all discovered vehicles as a tuple snapshot, in both runtime modes.
- Added source-scoped application handlers with component, vehicle and runtime
  precedence, cancellation and explicit replacement. Async handlers run on the
  caller's loop and are tracked through shutdown.
- Completed async runtime message streams, raw subscriptions, sends, waits and
  application calls. Added separate lifecycle queue capacity and delivery fault
  reporting without adding per-vehicle threads.
- Discover vehicles from autopilot heartbeats and their components from incoming
  traffic on one shared MAVLink connection. Source-indexed dispatch, bounded
  per-source telemetry history and one shared liveness monitor keep vehicle
  count independent of reader/monitor thread count.
- Added `vehicles.get(id)`, snapshot iteration, `wait_for(timeout=...)` and
  explicit removal of disconnected endpoints. Reconnection preserves endpoint
  objects and subscriptions. Component lookup, waits and lifecycle hooks are
  available directly through each vehicle.
- Added vehicle/component `subscribe`, `latest`, `history`, message waits,
  targeted sending, named message-rate requests and application requests.
  Fleet subscriptions include vehicles discovered after registration, while
  component discovery and connection hooks live directly on each vehicle.
- Added named lifecycle actions and string-based `on`, both accepting callbacks
  or decorators. Subscriptions support cancellation and `once=True`.
- Added `AsyncMavlinkRuntime` and async vehicle/component scopes. Registration
  and lookup stay synchronous; waits and transport operations are awaitable.
  A bounded callback queue uses one consumer on the caller's event loop,
  reports overflow counts and cancels outstanding deliveries during shutdown.
- Added multi-source isolation, callback lifecycle, shutdown, reconnect,
  cancellation and queue overflow tests, plus routing benchmarks at 1, 10 and
  100 discovered vehicles.

### Changed

- Removed the public vehicle component collection. Use
  `vehicle.get_component(id)` for one component and `get_components()` for a
  snapshot. Component waits, removal and discovery/connection hooks now live
  directly on the vehicle; fleet-wide `vehicles.get_component(id)` is unchanged.
- `MavlinkRuntime.on()` now registers lifecycle actions, not raw message
  subscriptions. Replace `runtime.on(message_type, callback)` with
  `runtime.subscribe(message_type, callback)` for raw messages, or use
  `vehicle.subscribe(...)` for source-scoped message envelopes.
- Multi-vehicle applications target discovered vehicle/component objects.
  The low-level connection/router APIs still expose their shared transport
  state; their default target and global cache are not per-vehicle state.

### Fixed

- Serialize synchronous runtime startup and shutdown so close cannot finish
  while an earlier startup can still reopen the transport. Owned worker threads
  reject conflicting lifecycle operations instead of waiting on their own join.
- Snapshot synchronous telemetry subscribers on receipt. Later registrations
  no longer receive queued older messages, while cancellation is still checked
  at delivery. Lifecycle actions retain delivery-time registration lookup.
- Isolate synchronous lifecycle delivery from telemetry overflow. Expose fatal
  callback-worker exits as runtime faults and reject new operations until restart.
- Run remaining hooks after ordinary hook failures, report success/cleanup
  failures to local error hooks, and preserve multiple failures together.
- Move SQLite commits to a bounded background writer with flush/drain semantics
  and explicit overflow/disk errors; packet snapshot encoding remains synchronous.
- Modernize license metadata and align the package version with `1.5` instead
  of the stale `1.3.1`.
- Reject same-thread lifecycle re-entry, preventing a nested close during
  startup from leaving a closed runtime with a live transport.
- Complete history and runtime registration type annotations, including explicit
  latest-query parameters and JSON payload types. Validate source IDs, empty
  message types and invalid time ranges consistently across storage backends.
- Stop bounded memory history queries after finding enough newest matches,
  avoiding a full scan and intermediate result list for common latest/tail reads.
- Keep latest vehicle/component messages independently of bounded history;
  router latest values are retained per source and message type as well.
- Reject new async runtime sends and waits consistently after a delivery
  fault, matching scoped operations. Wake pending scoped waits on fault
  notification while keeping snapshot lookups available for inspection.
- Make discovered identity fields read-only so commands cannot diverge from
  the source registry. Reselect connected autopilots after removal or timeout.
- Isolate callback cancellation from the shared async consumer. Keep telemetry
  overflow separate from lifecycle delivery; action overflow now faults visibly.
- Resolve queued lifecycle callbacks in delivery order so discovery callbacks
  can install the following connection and component hooks.
- Make concurrent close callers wait for cleanup in both runtime modes and
  protect shared async shutdown from caller cancellation.
- Cover source-handler precedence, async API parity, cancellation, identity,
  autopilot selection, discovery overflow and concurrent shutdown with tests.
- Preserve the heartbeat consumed during connection setup for vehicle discovery.

- Run event history predicates outside the history lock against a stable
  snapshot. Predicates can now append or clear history without invalidating
  iteration, and slow predicates do not hold up other history writers.
  Filtered reads copy the retained history for consistency; unfiltered limited
  reads keep their bounded-copy fast path.

## [v1.4] - 2026-09-07

### Added

- Added blocking waits and explicit history removal for chain and parallel
  executions. Completed execution history is bounded and configurable through
  `MissionEngine(execution_history=...)`.
- Added optional engine-wide active and queued mission limits for predictable
  backpressure under load.
- Added bounded replay buffers and periodic schedule capacity to both event bus
  implementations.
- Added the root-level `run_benchmarks.py`, which measures model, synchronous
  and asynchronous event, dependency, MAVLink and mission paths. It reports
  normalized wall time, CPU time and memory use as a table or JSON.
- Added deterministic concurrency tests for in-flight dependency removal,
  callback-driven dispatcher shutdown, response source correlation, blocked
  mission timeouts, group cleanup, background ownership and event replay
  cancellation.
- Moved the complete test launcher from `tests/run.py` to the repository root
  as `run_tests.py`, next to the benchmark launcher.

### Changed

- Replaced repeated full mission registry scans with active, queued, resource
  owner and successful-type indexes. Queue promotion now considers queued
  missions only.
- Event history now reads an unfiltered latest value in constant time and scans
  backward only as far as a limited query requires. Limited and filtered reads
  no longer copy the complete history before scanning it.
- Dependency resource tracking now uses identity indexes instead of repeatedly
  scanning every remembered object. Async cleanup remains deterministic when
  its caller is cancelled.
- Mission execution mappings preserve already validated immutable values across
  snapshot updates, avoiding repeated deep copies and JSON validation.
- Terminal missions owned by expired or explicitly forgotten orchestration
  runs are released from the engine registry with their snapshots.
- Parallel snapshots refresh child phases while running. Chain and group stop
  paths attempt cleanup for every child and report failures together.
- Kept the benchmark's terminal table within 90 columns, with compact headings
  and safely shortened labels; the complete values remain available as JSON.
- Reworded both README introductions around the repository's general-purpose
  scope without tying the core to a particular team or application.

### Fixed

- Kept failed mission workers in `STOPPING` while their thread is still alive,
  preserving resource ownership until cleanup can safely be retried.
- Prevented terminal missions from being unregistered while their worker is
  still returning from its final callback.
- Prevented transition callbacks from launching new work while the mission
  engine is stopping, and observed timeouts even when `start()` is blocked.
- Closed registration and shutdown races in dependency caches, including child
  scope resources, replacement during initialization and same-loop sync waits
  on async factories.
- Prevented one failing dependency cleanup from skipping later resources and
  guaranteed context reset after sync or async shutdown errors.
- Prevented one-worker event executors from deadlocking on a reentrant publish
  and removed subscriptions whose async replay is cancelled.
- Made parametrized generic event filters and action models constructible on
  Python 3.10 while retaining their frozen public contract.
- Suppressed dispatcher responses after any shutdown callback and required a
  correlated peer response to come from the requested MAVLink source.
- Avoided repeated router history scans while waiting for a predicate.
- Tightened MAVLink endpoint and application codec validation for non-finite
  timeouts and malformed wire field types.
- Detached caller-owned sequences and read-only mapping proxies before storing
  them in frozen models, and fixed nested model serialization.
- Closed owner-registration and early parallel-failure races in mission
  orchestration. Registered siblings are now terminated along with running or
  queued siblings.

## [v1.3.1] - 2026-08-18

### Added

- Added an immutable execution context for mission chains. Each run now carries
  its own input, metadata, previous terminal state and completed stage results.
- Added named parallel mission groups with aggregate snapshots and explicit
  wait, cancel-remaining and stop-remaining failure policies.
- Added parallel stages to mission chains, allowing flows such as
  `prepare -> parallel work -> finish` with result handoff between stages.
- Added engine-owned background missions that can follow a mission, chain or
  parallel group lifecycle through explicit owner and failure policies.
- Added deterministic orchestration tests covering isolated chain runs, retry
  context, failure continuation, timeout and cancellation, parallel execution,
  resource conflicts, result aggregation and background ownership.

### Changed

- Split mission orchestration into focused chain, parallel and background
  executors. A small internal coordinator connects them while `MissionEngine`
  remains the only public execution facade.
- Moved execution definitions and snapshots out of the general lifecycle model
  module, keeping runtime events and orchestration data in separate files.
- Renamed `MissionChain.mission_types` to `MissionChain.stages` and replaced
  `MissionChainSnapshot.current_mission_type` with `current_stage`, reflecting
  that a chain entry may be a mission, a named node or a parallel stage.
- Registered missions can now be stopped or cancelled before their first
  launch, which makes reentrant group and background termination deterministic.
- Repeated mission types in a chain receive distinct result keys. Applications
  can also use `MissionNode` when a domain-meaningful node name is preferred.
- Expanded both guides with practical chain handoff, controlled parallel stage,
  background ownership and cancellation propagation examples.
- Updated package metadata to version `1.3.1`.

### Removed

- Removed the chain proxy methods from `MissionScheduler`; chain operations now
  belong exclusively to `MissionEngine`.
- Removed `MissionOrchestrator` from package-level exports and removed the
  direct `Mission.chain_context` shortcut. Missions read execution data through
  the explicit `Mission.runtime.chain_context` boundary.
- Removed public-module identity rewriting that existed only to preserve the
  previous internal file layout.

### Fixed

- Prevented chain context and results from leaking between concurrent or later
  executions of the same chain definition.
- Preserved the same chain context across retries and removed it from a mission
  runtime after the mission reaches a terminal state.
- Ensured chain, group and owner termination is propagated through normal
  mission lifecycle commands instead of bypassing cleanup.
- Prevented reentrant start events from launching children after their group or
  owner has already been stopped.

## [v1.3] - 2026-08-13

### Added

- Added deterministic tests for concurrent mission launch, guarded completion,
  mixed sync/async dependency resolution, event replay ordering, cross-thread
  asyncio channel shutdown and dispatcher self-stop.
- Added a GitHub Actions matrix for Python 3.10 through 3.14, an installed-wheel
  check and an optional real `pymavlink` UDP loopback test.

### Changed

- Mission queue age now uses a monotonic clock, and repeated launch calls for
  one mission share a single serialized launch path.
- Frozen mission, application-packet, handler-result and remote-log mappings are
  recursively immutable. Serialization still returns detached mutable data.
- Sync and async dependency resolution now coordinate through the same cache
  initialization gate for singleton and scoped lifetimes.
- Event replay is delivered before live events that arrive while a subscription
  is being established.
- `MavlinkAsyncChannel` now uses one thread-safe, latest-biased bounded queue.
  Overflow consistently drops the oldest pending message, and stop safely wakes
  receivers without touching an asyncio queue from another thread.
- Application fragment cleanup is amortized and tracks byte counts incrementally
  instead of rescanning every in-flight fragment on each arrival.
- Updated package metadata to version `1.3.0`.

### Fixed

- Prevented `MissionLifecycle.complete()` from changing stop or cleanup state
  before validating that the mission is running.
- Prevented stale queued snapshots from timing out or promoting a newer mission
  generation.
- Allowed an application handler to stop its own dispatcher without attempting
  to join its current worker thread. Late responses from the stopped session
  remain suppressed.

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

[Unreleased]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.7.2...HEAD
[v1.7.2]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.7.1...v1.7.2
[v1.7.1]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.7...v1.7.1
[v1.7]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.6...v1.7
[v1.6]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.5...v1.6
[v1.5]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.4...v1.5
[v1.4]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.3.1...v1.4
[v1.3.1]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.3...v1.3.1
[v1.3]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.2...v1.3
[v1.2]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.1.1...v1.2
[v1.1.1]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.1...v1.1.1
[v1.1]: https://github.com/TahsinCr/vehicle-autonomy-core/compare/v1.0...v1.1
[v1.0]: https://github.com/TahsinCr/vehicle-autonomy-core/releases/tag/v1.0
