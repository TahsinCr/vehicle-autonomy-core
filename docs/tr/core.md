[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/core.md) | **Türkçe**

# Core soyutlamaları

Bu tipler `src.core` üzerinden import edilir.

## `Model`

`Model`, küçük domain ve snapshot nesneleri için ortak serialization tabanıdır.
`to_dict()` public dataclass field'larını, normal attribute'ları ve slot'ları
recursive biçimde dönüştürür. `_` ile başlayan isimler dışarı verilmez.

Desteklenen iç değerler: başka `Model` nesneleri, dataclass'lar, mapping'ler,
tuple/list/set/frozenset ve scalar değerlerdir. Dönen mapping ve mutable değerler
model state'inden ayrıdır.

```python
from dataclasses import dataclass
from src.core import Model

@dataclass(frozen=True, slots=True)
class Position(Model):
    latitude: float
    longitude: float
    tags: frozenset[str] = frozenset()

payload = Position(39.9, 32.8, frozenset({"home"})).to_dict()
```

Public üye: `Model.to_dict() -> dict[str, Any]`.

## `Service`

`Service`, `start()` ve `stop()` abstract metotlarından oluşan en küçük lifecycle
sözleşmesidir. `close()` ve context manager desteği uygun concrete servislerce
sunulur; base sözleşmenin parçası değildir.

```python
from src.core import Service

class Worker(Service):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...
```

## Structural protocol'ler

`ReadableValue[T]`, read-only `current` property sunan nesneyi; `Closable`,
`close()` sunan nesneyi tarif eder. Bunlar typing sözleşmesidir ve root
`__all__` içinde değildir.
