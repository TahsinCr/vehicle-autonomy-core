"""Public dependency injection API."""

from .container import (
    BaseDependencyContainer,
    DependencyContainer,
    get_current_container,
    get_default_container,
    set_default_container,
)
from .registration import DEFAULT_PRIORITY, DependencyMap, Inject, Lifetime, MISSING, Token
from .errors import (
    AsyncDependencyError,
    CircularDependencyError,
    DependencyError,
    DependencyNotFoundError,
    DependencyResolutionError,
)
from .injection import injection


# Keep the long-standing public module identity stable for introspection and
# pickle compatibility while implementation lives in focused submodules.
for _public_object in (
    AsyncDependencyError,
    BaseDependencyContainer,
    CircularDependencyError,
    DependencyContainer,
    DependencyError,
    DependencyNotFoundError,
    DependencyResolutionError,
    Inject,
    Lifetime,
    get_current_container,
    get_default_container,
    injection,
    set_default_container,
):
    _public_object.__module__ = __name__
del _public_object


__all__ = [
    "AsyncDependencyError",
    "BaseDependencyContainer",
    "CircularDependencyError",
    "DEFAULT_PRIORITY",
    "DependencyContainer",
    "DependencyError",
    "DependencyMap",
    "DependencyNotFoundError",
    "DependencyResolutionError",
    "Inject",
    "Lifetime",
    "Token",
    "get_current_container",
    "get_default_container",
    "injection",
    "set_default_container",
]
