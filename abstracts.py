from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import fields, is_dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable


class Model(ABC):
    """Domain model contract independent from UI and storage technologies."""

    __slots__ = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the model's public fields as a dictionary."""

        if is_dataclass(self):
            return {
                field.name: getattr(self, field.name)
                for field in fields(self)
                if not field.name.startswith("_")
            }

        values = {
            name: value
            for name, value in getattr(self, "__dict__", {}).items()
            if not name.startswith("_")
        }
        for model_type in type(self).__mro__:
            slots = model_type.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for name in slots:
                if not name.startswith("_") and hasattr(self, name):
                    values[name] = getattr(self, name)
        return values


class Service(ABC):
    """Universal contract for services with a lifecycle."""

    __slots__ = ()

    @abstractmethod
    def start(self) -> None:
        """Prepare the service for use."""

    @abstractmethod
    def stop(self) -> None:
        """Close resources owned by the service safely."""


T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class ReadableValue(Protocol[T_co]):
    """Generic read contract exposing the latest value."""

    @property
    def current(self) -> T_co: ...


@runtime_checkable
class Closable(Protocol):
    def close(self) -> None: ...
