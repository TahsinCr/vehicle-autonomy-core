**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/events.md)

# Events

The event package offers matching synchronous and asyncio-native APIs. Choose
the bus that matches the caller; callback mode is validated at registration.

## Synchronous `EventBus`

```text
EventBus(
    *,
    history=None,
    error_policy=ErrorPolicy.ISOLATE,
    executor=None,
    replay_buffer_limit=1000,
    max_schedules=64,
    shutdown_timeout=5.0,
    actions=None,
    on_before=None,
    on_after=None,
    on_error=None,
    on_timeout=None,
)
```

- `history`: `None`, an integer capacity, or an `EventHistory` implementation.
- `executor`: optional executor for subscriber execution.
- `replay_buffer_limit`: live events buffered behind one replaying subscriber.
- `max_schedules`: maximum active `publish_every()` schedules.
- `shutdown_timeout`: total time `close()` waits for schedule threads.
- `actions` or individual `on_*`: bus-level hooks; do not combine both forms.

### Bus operations

| Method | Parameters | Result |
|---|---|---|
| `subscribe(callback, *, event_filter=None, event_type=None, predicate=None, once=False, times=None, replay=0)` | delivery policy | `Subscription` |
| `once(callback, *, ... , replay=0)` | one accepted event | `Subscription` |
| `publish(event)` | event value | `PublishResult` |
| `wait_for(*, ..., timeout=None)` | filter and timeout | event or `None` |
| `query(*, ..., limit=None)` | retained-history query | oldest-first tuple |
| `latest(*, ...)` | retained-history query | last match or `None` |
| `publish_every(event, interval, *, times=None, immediately=True)` | periodic publish | `Subscription` |
| `clear()` | none | removes subscribers |
| `close()` | none | closes subscriptions and schedules |

Callbacks run on the publishing thread without an executor. A slow callback can
therefore slow its producer. `close()` raises `EventShutdownTimeoutError` if a
schedule remains inside user code beyond `shutdown_timeout`; it never kills a
thread. The live schedule remains owned, so calling `close()` again after the
callback exits completes the join.

## `AsyncEventBus`

Constructor parameters match the sync bus except:

- `delivery_mode=DeliveryMode.SEQUENTIAL` replaces `executor`;
- hooks and subscribers must be coroutine functions;
- shutdown is `await bus.close()`;
- `publish`, `wait_for`, `publish_every` and subscription cancellation are awaited;
- `publish_threadsafe(event)` may be called from another thread and returns a
  `concurrent.futures.Future[PublishResult]`.

```python
from src.core.events import AsyncEventBus, DeliveryMode

async def main() -> None:
    bus = AsyncEventBus[Telemetry](
        history=100,
        delivery_mode=DeliveryMode.CONCURRENT,
    )

    @bus.subscribe
    async def consume(event: Telemetry) -> None:
        ...

    await bus.publish(Telemetry(...))
    await bus.close()
```

Sequential mode preserves subscriber order. Concurrent mode awaits all matched
subscribers and returns errors in stable result form.

## Filtering and replay

`EventFilter(event_type=None, predicate=None)` combines an `isinstance` check
with a synchronous predicate. The equivalent `event_type=` and `predicate=`
arguments are available directly on bus methods.

```python
events.subscribe(
    handle_warning,
    event_type=StatusEvent,
    predicate=lambda event: event.level >= 30,
    replay=10,
)
```

Replay is an atomic subscription boundary. If its pending buffer overflows,
only that subscription is cancelled; the failure appears in `PublishResult` and
healthy subscribers still receive the event.

## Results, statistics and policies

`PublishResult(matched, delivered, failed, errors)` has `successful`, true when
`failed == 0`. `EventBusStats(published, delivered, failed)` is available through
`bus.stats`. `subscriber_count` reports active registrations on `BaseEventBus`,
`EventBus` and `AsyncEventBus`.

`ErrorPolicy.ISOLATE` returns subscriber failures. `ErrorPolicy.RAISE` raises
the failure (or aggregate) after delivery. `DeliveryMode` is `SEQUENTIAL` or
`CONCURRENT` for async buses.

## Callback policies

Higher-level modules use `CallbackSubscription` for per-registration behavior:

```python
subscription = vehicle.subscribe(
    "ATTITUDE",
    handle_attitude,
    once=False,
    max_calls=100,
    frequency_hz=10.0,
    timeout=0.05,
    predicate=lambda event: event.message.roll is not None,
    enabled=True,
)

@subscription.on_error
def callback_failed(context):
    ...
```

Constructor policy parameters are `asynchronous`, `once`, `max_calls`,
`frequency_hz`, `timeout`, `predicate`, `enabled`, and the five hooks
`on_before`, `on_success`, `on_error`, `on_timeout`, `on_after`.

Methods/properties:

- `enable()`, `disable()`, `enabled`, `active`, `cancel()`;
- `invoke(event)` and `invoke_async(event)`;
- hook decorators `on_before`, `on_success`, `on_error`, `on_timeout`, `on_after`.

Hooks receive `CallbackContext(event, result, error, elapsed)`. Sync timeout is
observational: the callback finishes, then `CallbackTimeoutError` is reported.
Async timeout cancels the awaited callback within its execution budget.

## Named engines

`EventEngine` manages named sync channels; `AsyncEventEngine` provides the same
surface for async channels.

```python
engine = EventEngine(history=50)
engine.start()
engine.subscribe("telemetry", consume)
engine.publish("telemetry", sample)
engine.stop()
```

Both expose `add`, `remove`, `channel`, `subscribe`, `once`, `publish`,
`publish_every`, `wait_for`, `start`, `stop`, and `close`. Missing channels are
created using engine defaults. `add(name, bus)` installs an explicitly configured
bus. `channel_names` returns the current immutable name list.

## History and subscriptions

`EventHistory` defines `append`, `latest`, `query` and `clear`.
`MemoryEventHistory(capacity=1000)` is the built-in thread-safe bounded store.
`Subscription` and `AsyncSubscription` expose `id`, `active` and cancellation;
cancellation is idempotent.

## Errors

- `EventBusError`
- `EventBusClosedError`
- `InvalidEventHandlerError`
- `CallbackTimeoutError`
- `EventShutdownTimeoutError`

`EventBusActions` and `AsyncEventBusActions` bundle bus-level `on_before`,
`on_after`, `on_error` and `on_timeout`. Error hooks receive
`EventErrorContext(event, error)`; timeout hooks receive
`EventTimeoutContext(event_filter, timeout)`.
