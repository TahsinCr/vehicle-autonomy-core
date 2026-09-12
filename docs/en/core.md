**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/core.md)

# Core abstractions

Import these types from `src.core`.

## `Model`

`Model` is the common serialization base for small domain and snapshot objects.
`to_dict()` serializes public dataclass fields, normal attributes
and slots recursively. Names beginning with `_` are omitted.

Supported nested values include:

- another `Model`;
- dataclasses;
- mappings;
- tuples, lists, sets and frozen sets;
- enums and ordinary scalar values.

Tuple-like values stay tuples. Mappings and nested mutable values are detached
from model state.

```python
from dataclasses import dataclass
from src.core import Model

@dataclass(frozen=True, slots=True)
class Position(Model):
    latitude: float
    longitude: float
    tags: frozenset[str] = frozenset()

position = Position(39.9, 32.8, frozenset({"home"}))
payload = position.to_dict()
```

Public API:

| Member | Purpose |
|---|---|
| `Model.to_dict()` | Return recursively serialized public state |

## `Service`

`Service` is the lifecycle base for components that can start and stop. Concrete
services implement `start()` and `stop()`. Context-manager support and `close()`
are conveniences supplied by concrete services when appropriate; they are not
part of this minimal base contract.

```python
from src.core import Service

class Worker(Service):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

worker = Worker()
worker.start()
try:
    ...
finally:
    worker.stop()
```

| Member | Purpose |
|---|---|
| `start()` | Acquire resources and begin operation |
| `stop()` | Stop operation and release owned resources |

## Structural protocols

`ReadableValue[T]` describes objects exposing a read-only `current` property.
`Closable` describes objects with `close()`. They are typing contracts rather
than runtime managers and are intentionally not part of the root `__all__`.
