from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import fields, is_dataclass
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, runtime_checkable


class Model(ABC):
    """Domain model contract independent from UI and storage technologies."""

    __slots__ = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the model's public fields as a dictionary."""

        if is_dataclass(self):
            return {
                field.name: _copy_model_value(getattr(self, field.name))
                for field in fields(self)
                if not field.name.startswith("_")
            }

        values = {
            name: _copy_model_value(value)
            for name, value in getattr(self, "__dict__", {}).items()
            if not name.startswith("_")
        }
        for model_type in type(self).__mro__:
            slots = model_type.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for name in slots:
                if not name.startswith("_") and hasattr(self, name):
                    values[name] = _copy_model_value(getattr(self, name))
        return values


def _freeze_model_value(value: Any) -> Any:
    """Detach and recursively freeze a value stored by a public model."""

    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {deepcopy(key): _freeze_model_value(item) for key, item in value.items()}
        )
    if isinstance(value, tuple):
        frozen = tuple(_freeze_model_value(item) for item in value)
        return value if all(a is b for a, b in zip(value, frozen)) else frozen
    if isinstance(value, list):
        return tuple(_freeze_model_value(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze_model_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_model_value(item) for item in value)
    return deepcopy(value)


def _copy_model_value(value: Any, *, lists: bool = False) -> Any:
    """Return a detached, mutable representation of a frozen model value."""

    if isinstance(value, Mapping):
        return {
            deepcopy(key): _copy_model_value(item, lists=lists)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        copied = tuple(_copy_model_value(item, lists=lists) for item in value)
        return list(copied) if lists else copied
    if isinstance(value, frozenset):
        return {_copy_model_value(item, lists=lists) for item in value}
    return deepcopy(value)


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
