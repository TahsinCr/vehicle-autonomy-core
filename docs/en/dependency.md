**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/dependency.md)

# Dependency injection

The dependency package provides explicit registration, automatic constructor
injection, sync/async resolution, nested scopes and deterministic cleanup.

```python
from src.core.dependency import DependencyContainer, Inject, Lifetime, injection
```

## Lifetimes

| Lifetime | Instance behavior | Cleanup owner |
|---|---|---|
| `Lifetime.TRANSIENT` | New instance per resolution | Caller |
| `Lifetime.SINGLETON` | One instance at the provider owner | Registering container |
| `Lifetime.SCOPED` | One instance per scope | Scope container |

`close()` or `aclose()` is detected for cached resources. Cleanup runs in
reverse creation order, attempts every resource and raises an `ExceptionGroup`
when several fail. Failed resources remain owned and can be retried. Concurrent
cleanup claims each instance once, preventing double-close.

A failed unregister leaves the token in cleanup-pending state. The same token
cannot be registered again until `unregister()` or `unregister_async()` closes
the old resource successfully. Concurrent unregister callers share one disposal
attempt. A failed container-wide cleanup sets `cleanup_pending`; registration,
resolution and new scopes remain blocked until shutdown completes the remaining
cleanup. Successful shutdown is terminal. A child scope also stops resolving
fallback providers as soon as its parent starts shutting down.

## `DependencyContainer`

Constructor:

```text
DependencyContainer(*, parent: DependencyContainer | None = None,
                    auto_wire: bool = True)
```

`parent` supplies fallback registrations. `auto_wire=True` allows unregistered
concrete classes to be built from their annotated constructors.

### Registration methods

All registration methods return the container for chaining.

| Method | Important parameters | Behavior |
|---|---|---|
| `register()` | `token`, `provider`, `abstract`, `concrete`, `factory`, `instance`, `lifetime`, `dependencies`, `priority` | General registration entry point |
| `singleton()` | same selection arguments | Cache once at provider owner |
| `scoped()` | same, without ready `instance` | Cache once per scope |
| `transient()` | same, without ready `instance` | Build for every resolution |
| `instance()` | `token`, `instance`, `abstract`, `priority` | Register an already-created singleton |
| `provider()` | `token`, `abstract`, `lifetime`, `dependencies`, `priority` | Decorator for a factory/class |
| `unregister()` | `token` | Remove and synchronously dispose unreferenced cached values |
| `unregister_async()` | `token` | Remove and await async cleanup |

Exactly one provider source should be selected. `token`/`abstract` chooses the
lookup key; `provider`/`concrete`/`factory`/`instance` chooses construction.
`dependencies` maps callable parameter names to dependency tokens. Lower
numeric `priority` values warm first.

When the token is inferred from a provider return annotation, an invalid or
unresolvable forward reference raises `DependencyResolutionError` at
registration time instead of silently dropping inference.

```python
container = DependencyContainer()
container.instance("settings", settings)
container.singleton(Database, factory=create_database,
                    dependencies={"config": "settings"})

@container.provider(lifetime=Lifetime.SCOPED)
def repository(database: Database) -> Repository:
    return Repository(database)
```

Replacing a token first retires and disposes its old cached object. Use the
async registration lifecycle when the old object has asynchronous cleanup.

### Resolution and construction

| Method | Parameters | Returns |
|---|---|---|
| `resolve(token)` | hashable token or type | resolved value |
| `resolve_async(token)` | token | awaited resolved value |
| `build(factory, *, dependencies=None)` | callable/class | transient constructed value |
| `build_async(...)` | callable/class | awaited constructed value |
| `can_resolve(token)` | token | whether resolution is possible |
| `has(token)` | token | whether directly registered |
| `registered_tokens()` | none | local tokens as a tuple |
| `create_scope()` | none | child scope container |
| `warmup(tokens=None, *, lifetimes=(SINGLETON,))` | optional selection | eagerly resolve registrations |
| `warmup_async(...)` | optional selection | async eager resolution |
| `shutdown()` | none | sync deterministic cleanup |
| `shutdown_async()` | none | async deterministic cleanup |
| `closed` | property | whether terminal shutdown completed |
| `cleanup_pending` | property | whether failed global cleanup must be retried |

`DependencyCleanupPendingError` reports token reuse while old cleanup remains;
`DependencyContainerClosedError` reports use after successful shutdown. Sync
resolution rejects coroutine providers and async-only cleanup with
`AsyncDependencyError`; it never creates a hidden event loop.

## Injection

`Inject(token=MISSING, optional=False)` may be used as a default value or in
`typing.Annotated`. `injection()` wraps a function or class and resolves missing
arguments from a selected/current/default container.

```python
from typing import Annotated
from src.core.dependency import Inject, injection

@injection(strict=True)
def handler(
    repository: Repository,
    clock: Annotated[Clock, Inject()],
    audit: Audit | None = Inject("audit", optional=True),
) -> None:
    ...
```

Explicit caller arguments are never overwritten. `strict=True` reports missing
or unresolved annotated dependencies rather than leaving the parameter to
ordinary Python argument validation.

Signature:

```text
injection(target=None, *, container=None, dependencies=None,
          strict=False, **named_dependencies)
```

The same method is available as `container.inject(...)`.

## Application composition roots

Subclass `BaseDependencyContainer` and implement `configure()`:

```python
class ApplicationDependencies(BaseDependencyContainer):
    def configure(self) -> None:
        self.singleton(Database)
        self.scoped(UnitOfWork)

dependencies = ApplicationDependencies(set_as_default=True)
```

Constructor parameters are `container`, `parent`, `set_as_default` and
`auto_wire`. It delegates registration, resolution, scopes, injection, warmup
and shutdown to its `container` property.

## Ambient container helpers

| Function | Purpose |
|---|---|
| `get_current_container()` | Context-local container, falling back to default |
| `get_default_container()` | Process default container |
| `set_default_container(container)` | Replace process default |

Entering a container sets it as current and always resets the context variable,
even if shutdown fails.

## Errors and aliases

- `DependencyError` — package base error
- `DependencyNotFoundError` — token cannot be resolved
- `DependencyResolutionError` — invalid provider or construction failure
- `CircularDependencyError` — dependency cycle, including cross-thread/task
- `AsyncDependencyError` — async operation requested from sync path
- `Token` — `Hashable | type[Any]`
- `DependencyMap` — mapping from parameter name to token
- `DEFAULT_PRIORITY` — `100`
