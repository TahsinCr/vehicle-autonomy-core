"""Dependency container exception hierarchy."""

from __future__ import annotations


class DependencyError(Exception):
    """Base dependency-container error."""


class DependencyNotFoundError(DependencyError):
    """Raised when no provider exists for a token."""


class DependencyResolutionError(DependencyError):
    """Raised when a dependency cannot be produced deterministically."""


class CircularDependencyError(DependencyResolutionError):
    """Raised for dependency cycles such as A -> B -> A."""


class AsyncDependencyError(DependencyResolutionError):
    """Raised when an async resource is used through the synchronous API."""
