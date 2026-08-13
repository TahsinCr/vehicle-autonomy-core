"""Dependency registration, scopes, resolution, and public container lifecycle."""

from __future__ import annotations

import contextvars
import inspect
import threading
from collections.abc import Callable, Iterable
from typing import Any

from .annotations import (
    choose_factory,
    choose_token,
    ensure_hashable_token,
    infer_token_from_factory,
    is_direct_instance,
    normalize_dependencies,
    normalize_priority,
)
from .registration import (
    DEFAULT_PRIORITY,
    DependencyMap,
    Lifetime,
    InitializationGate,
    MISSING,
    Provider,
    ProviderCallable,
    Registration,
    T,
    Token,
)
from .errors import AsyncDependencyError, DependencyNotFoundError, DependencyResolutionError
from .injection import injection, resolve_missing_kwargs, resolve_missing_kwargs_async
from .lifecycle import (
    ResourceTracker,
    cached_instances,
    dispose_many,
    dispose_many_async,
    requires_async_disposal,
)
from .resolution import (
    can_autowire,
    close_awaitable,
    enter_resolution,
    exit_resolution,
    format_token,
)


_default_container: DependencyContainer | None = None
_current_container: contextvars.ContextVar[DependencyContainer | None] = (
    contextvars.ContextVar("current_dependency_container", default=None)
)


class DependencyContainer:
    """Synchronous and asynchronous dependency injection container."""

    __slots__ = (
        "auto_wire",
        "parent",
        "_context_tokens",
        "_providers",
        "_scope_cache",
        "_scope_initializers",
        "_scope_lock",
        "_tracker",
    )

    def __init__(
        self,
        *,
        parent: DependencyContainer | None = None,
        auto_wire: bool = True,
    ) -> None:
        self.parent = parent
        self.auto_wire = auto_wire
        self._providers: dict[Token, Provider] = {}
        self._scope_cache: dict[Token, Any] = {}
        self._scope_lock = threading.RLock()
        self._scope_initializers: dict[Token, InitializationGate] = {}
        self._tracker = ResourceTracker()
        self._context_tokens: list[
            contextvars.Token[DependencyContainer | None]
        ] = []

    def __contains__(self, token: Token) -> bool:
        return self.has(token)

    def __enter__(self) -> DependencyContainer:
        self._context_tokens.append(_current_container.set(self))
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self.shutdown()
        finally:
            self._reset_current_container()

    async def __aenter__(self) -> DependencyContainer:
        self._context_tokens.append(_current_container.set(self))
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            await self.shutdown_async()
        finally:
            self._reset_current_container()

    def register(
        self,
        token: Token | None = None,
        provider: Any = MISSING,
        *,
        abstract: Token | None = None,
        concrete: Any = MISSING,
        factory: Any = MISSING,
        instance: Any = MISSING,
        lifetime: Lifetime | str = Lifetime.TRANSIENT,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        """Register a class, factory, or ready instance for a token."""

        registration = self._normalize_registration(
            token=token,
            provider=provider,
            abstract=abstract,
            concrete=concrete,
            factory=factory,
            instance=instance,
            lifetime=lifetime,
            dependencies=dependencies,
            priority=priority,
        )
        if (
            registration.token in self._providers
            or registration.token in self._scope_cache
        ):
            self.unregister(registration.token)
        self._providers[registration.token] = Provider(
            token=registration.token,
            factory=registration.factory,
            lifetime=registration.lifetime,
            dependencies=registration.dependencies,
            priority=registration.priority,
            instance=registration.instance,
        )
        if registration.instance is not MISSING:
            self._tracker.remember(registration.instance)
        return self

    def singleton(
        self,
        token: Token | None = None,
        provider: Any = MISSING,
        *,
        abstract: Token | None = None,
        concrete: Any = MISSING,
        factory: Any = MISSING,
        instance: Any = MISSING,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.register(
            token,
            provider,
            abstract=abstract,
            concrete=concrete,
            factory=factory,
            instance=instance,
            lifetime=Lifetime.SINGLETON,
            dependencies=dependencies,
            priority=priority,
        )

    def transient(
        self,
        token: Token | None = None,
        provider: Any = MISSING,
        *,
        abstract: Token | None = None,
        concrete: Any = MISSING,
        factory: Any = MISSING,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.register(
            token,
            provider,
            abstract=abstract,
            concrete=concrete,
            factory=factory,
            lifetime=Lifetime.TRANSIENT,
            dependencies=dependencies,
            priority=priority,
        )

    def scoped(
        self,
        token: Token | None = None,
        provider: Any = MISSING,
        *,
        abstract: Token | None = None,
        concrete: Any = MISSING,
        factory: Any = MISSING,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.register(
            token,
            provider,
            abstract=abstract,
            concrete=concrete,
            factory=factory,
            lifetime=Lifetime.SCOPED,
            dependencies=dependencies,
            priority=priority,
        )

    def instance(
        self,
        token: Token | None = None,
        instance: Any = MISSING,
        *,
        abstract: Token | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.register(
            token,
            abstract=abstract,
            instance=instance,
            lifetime=Lifetime.SINGLETON,
            priority=priority,
        )

    def provider(
        self,
        token: Token | None = None,
        *,
        abstract: Token | None = None,
        lifetime: Lifetime | str = Lifetime.TRANSIENT,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> Callable[[ProviderCallable | type[Any]], ProviderCallable | type[Any]]:
        def decorator(factory: ProviderCallable | type[Any]) -> ProviderCallable | type[Any]:
            self.register(
                token,
                abstract=abstract,
                factory=factory,
                lifetime=lifetime,
                dependencies=dependencies,
                priority=priority,
            )
            return factory

        return decorator

    def inject(
        self,
        target: Callable[..., T] | type[T] | None = None,
        *,
        dependencies: DependencyMap | None = None,
        strict: bool = False,
        **named_dependencies: Token,
    ) -> Callable[..., T] | type[T] | Callable[[Callable[..., T] | type[T]], Any]:
        return injection(
            target,
            container=self,
            dependencies=dependencies,
            strict=strict,
            **named_dependencies,
        )

    def unregister(self, token: Token) -> None:
        """Unregister a token and synchronously dispose its cached resources."""

        candidates = self._token_instances(token)
        async_only = next(
            (item for item in candidates if requires_async_disposal(item)),
            None,
        )
        if async_only is not None:
            raise AsyncDependencyError(
                f"{format_token(type(async_only))} async kapanıyor; "
                "unregister_async kullan."
            )
        dispose_many(self._detach_token_instances(token))

    async def unregister_async(self, token: Token) -> None:
        await dispose_many_async(self._detach_token_instances(token))

    def has(self, token: Token) -> bool:
        return self._find_provider(token) is not None

    def can_resolve(self, token: Token) -> bool:
        return self.has(token) or (self.auto_wire and can_autowire(token))

    def registered_tokens(self) -> tuple[Token, ...]:
        return tuple(sorted(self._providers, key=format_token))

    def create_scope(self) -> DependencyContainer:
        return DependencyContainer(parent=self, auto_wire=self.auto_wire)

    def resolve(self, token: Token) -> Any:
        return self._resolve_provider(self._get_or_autowire_provider(token))

    async def resolve_async(self, token: Token) -> Any:
        return await self._resolve_provider_async(self._get_or_autowire_provider(token))

    def build(
        self,
        factory: ProviderCallable | type[T],
        *,
        dependencies: DependencyMap | None = None,
    ) -> T:
        return self._call_factory(factory, normalize_dependencies(dependencies))

    async def build_async(
        self,
        factory: ProviderCallable | type[T],
        *,
        dependencies: DependencyMap | None = None,
    ) -> T:
        return await self._call_factory_async(factory, normalize_dependencies(dependencies))

    def warmup(
        self,
        tokens: Iterable[Token] | None = None,
        *,
        lifetimes: Iterable[Lifetime | str] = (Lifetime.SINGLETON,),
    ) -> None:
        for provider in self._warmup_providers(tokens, lifetimes):
            self.resolve(provider.token)

    async def warmup_async(
        self,
        tokens: Iterable[Token] | None = None,
        *,
        lifetimes: Iterable[Lifetime | str] = (Lifetime.SINGLETON,),
    ) -> None:
        for provider in self._warmup_providers(tokens, lifetimes):
            await self.resolve_async(provider.token)

    def shutdown(self) -> None:
        candidates = self._shutdown_instances()
        async_only = next(
            (item for item in candidates if requires_async_disposal(item)),
            None,
        )
        if async_only is not None:
            raise AsyncDependencyError(
                f"{format_token(type(async_only))} async kapanıyor; "
                "shutdown_async kullan."
            )
        dispose_many(self._detach_shutdown_instances())

    async def shutdown_async(self) -> None:
        await dispose_many_async(self._detach_shutdown_instances())

    def _normalize_registration(
        self,
        *,
        token: Token | None,
        provider: Any,
        abstract: Token | None,
        concrete: Any,
        factory: Any,
        instance: Any,
        lifetime: Lifetime | str,
        dependencies: DependencyMap | None,
        priority: int,
    ) -> Registration:
        selected_token = choose_token(token=token, abstract=abstract)
        selected_factory = choose_factory(
            provider=provider,
            concrete=concrete,
            factory=factory,
            instance=instance,
        )
        try:
            selected_lifetime = Lifetime(lifetime)
        except ValueError as exc:
            raise DependencyResolutionError(f"Geçersiz lifetime: {lifetime!r}.") from exc
        selected_instance = MISSING

        if selected_factory is MISSING:
            if selected_token is not None and inspect.isclass(selected_token):
                selected_factory = selected_token
            else:
                raise DependencyResolutionError(
                    "Dependency kaydı için token/abstract veya provider/concrete "
                    "belirtilmeli."
                )
        if selected_token is None:
            selected_token = infer_token_from_factory(selected_factory)
        if selected_token is None:
            raise DependencyResolutionError(
                "Token belirlenemedi. abstract=... veya token parametresi ver."
            )
        if instance is not MISSING:
            selected_instance = instance
            selected_lifetime = Lifetime.SINGLETON
        elif is_direct_instance(selected_factory):
            selected_instance = selected_factory
            selected_lifetime = Lifetime.SINGLETON
        ensure_hashable_token(selected_token)
        return Registration(
            token=selected_token,
            factory=selected_factory,
            lifetime=selected_lifetime,
            dependencies=normalize_dependencies(dependencies),
            priority=normalize_priority(priority),
            instance=selected_instance,
        )

    def _reset_current_container(self) -> None:
        if self._context_tokens:
            _current_container.reset(self._context_tokens.pop())

    def _find_provider(self, token: Token) -> Provider | None:
        provider = self._providers.get(token)
        if provider is not None:
            return provider
        return self.parent._find_provider(token) if self.parent is not None else None

    def _get_or_autowire_provider(self, token: Token) -> Provider:
        provider = self._find_provider(token)
        if provider is not None:
            return provider
        if self.auto_wire and can_autowire(token):
            return Provider(token=token, factory=token, lifetime=Lifetime.TRANSIENT)
        raise DependencyNotFoundError(
            f"{format_token(token)} için kayıtlı dependency bulunamadı."
        )

    def _warmup_providers(
        self,
        tokens: Iterable[Token] | None,
        lifetimes: Iterable[Lifetime | str],
    ) -> list[Provider]:
        selected_lifetimes = {Lifetime(item) for item in lifetimes}
        selected_tokens = set(tokens) if tokens is not None else None
        providers = [
            provider
            for provider in self._providers.values()
            if provider.lifetime in selected_lifetimes
            and (selected_tokens is None or provider.token in selected_tokens)
        ]
        return sorted(providers, key=lambda item: (item.priority, format_token(item.token)))

    def _resolve_provider(self, provider: Provider) -> Any:
        if provider.has_instance:
            return provider.instance
        stack_token = enter_resolution(provider.token)
        try:
            if provider.lifetime == Lifetime.TRANSIENT:
                return self._call_factory(provider.factory, provider.dependencies)
            if provider.lifetime == Lifetime.SCOPED:
                gate = self._get_scope_initializer(provider.token)
                return self._resolve_cached_sync(
                    gate,
                    lambda: self._scope_cache.get(provider.token, MISSING),
                    lambda value: self._store_scoped(provider.token, value),
                    lambda: self._call_factory(provider.factory, provider.dependencies),
                )
            return self._resolve_cached_sync(
                provider.initialization,
                lambda: provider.singleton,
                lambda value: self._store_singleton(provider, value),
                lambda: self._call_factory(provider.factory, provider.dependencies),
            )
        finally:
            exit_resolution(stack_token)

    async def _resolve_provider_async(self, provider: Provider) -> Any:
        if provider.has_instance:
            return provider.instance
        stack_token = enter_resolution(provider.token)
        try:
            if provider.lifetime == Lifetime.TRANSIENT:
                return await self._call_factory_async(
                    provider.factory, provider.dependencies
                )
            if provider.lifetime == Lifetime.SCOPED:
                gate = self._get_scope_initializer(provider.token)
                return await self._resolve_cached_async(
                    gate,
                    lambda: self._scope_cache.get(provider.token, MISSING),
                    lambda value: self._store_scoped(provider.token, value),
                    lambda: self._call_factory_async(
                        provider.factory, provider.dependencies
                    ),
                )
            return await self._resolve_cached_async(
                provider.initialization,
                lambda: provider.singleton,
                lambda value: self._store_singleton(provider, value),
                lambda: self._call_factory_async(
                    provider.factory, provider.dependencies
                ),
            )
        finally:
            exit_resolution(stack_token)

    def _call_factory(
        self,
        factory: ProviderCallable | type[T],
        dependencies: dict[str, Token],
    ) -> T:
        if inspect.iscoroutinefunction(factory):
            raise AsyncDependencyError(
                f"{format_token(factory)} async çalışıyor; "
                "resolve_async/build_async kullan."
            )
        kwargs = resolve_missing_kwargs(
            factory,
            args=(),
            kwargs={},
            dependencies=dependencies,
            container=self,
            strict=True,
        )
        result = factory(**kwargs)
        if inspect.isawaitable(result):
            close_awaitable(result)
            raise AsyncDependencyError(
                f"{format_token(factory)} awaitable döndürdü; "
                "resolve_async/build_async kullan."
            )
        return result

    async def _call_factory_async(
        self,
        factory: ProviderCallable | type[T],
        dependencies: dict[str, Token],
    ) -> T:
        kwargs = await resolve_missing_kwargs_async(
            factory,
            args=(),
            kwargs={},
            dependencies=dependencies,
            container=self,
            strict=True,
        )
        result = factory(**kwargs)
        return await result if inspect.isawaitable(result) else result

    def _provider_owner(self, provider: Provider) -> DependencyContainer:
        container: DependencyContainer | None = self
        while container is not None:
            if container._providers.get(provider.token) is provider:
                return container
            container = container.parent
        return self

    def _token_instances(self, token: Token) -> tuple[Any, ...]:
        values: list[Any] = []
        scoped = self._scope_cache.get(token, MISSING)
        if scoped is not MISSING:
            values.append(scoped)
        provider = self._providers.get(token)
        if provider is not None:
            values.extend(cached_instances(provider))
        return tuple(values)

    def _get_scope_initializer(self, token: Token) -> InitializationGate:
        with self._scope_lock:
            return self._scope_initializers.setdefault(token, InitializationGate())

    @staticmethod
    def _resolve_cached_sync(
        gate: InitializationGate,
        read: Callable[[], Any],
        store: Callable[[Any], None],
        create: Callable[[], Any],
    ) -> Any:
        while True:
            cached = read()
            if cached is not MISSING:
                return cached
            if gate.claim():
                break
            gate.wait()
        try:
            value = create()
            store(value)
            return value
        finally:
            gate.release()

    @staticmethod
    async def _resolve_cached_async(
        gate: InitializationGate,
        read: Callable[[], Any],
        store: Callable[[Any], None],
        create: Callable[[], Any],
    ) -> Any:
        while True:
            cached = read()
            if cached is not MISSING:
                return cached
            if gate.claim():
                break
            await gate.wait_async()
        try:
            value = await create()
            store(value)
            return value
        finally:
            gate.release()

    def _store_scoped(self, token: Token, value: Any) -> None:
        self._scope_cache[token] = value
        self._tracker.remember(value)

    def _store_singleton(self, provider: Provider, value: Any) -> None:
        provider.singleton = value
        self._provider_owner(provider)._tracker.remember(value)

    def _is_referenced(self, instance: Any) -> bool:
        if any(value is instance for value in self._scope_cache.values()):
            return True
        return any(
            cached is instance
            for provider in self._providers.values()
            for cached in cached_instances(provider)
        )

    def _detach_token_instances(self, token: Token) -> tuple[Any, ...]:
        candidates = self._token_instances(token)
        provider = self._providers.pop(token, None)
        self._scope_cache.pop(token, MISSING)
        with self._scope_lock:
            self._scope_initializers.pop(token, None)
        if provider is not None:
            provider.instance = MISSING
            provider.singleton = MISSING
        unreferenced = tuple(
            instance for instance in candidates if not self._is_referenced(instance)
        )
        ordered = self._tracker.ordered(unreferenced)
        self._tracker.forget(ordered)
        return ordered

    def _shutdown_instances(self) -> tuple[Any, ...]:
        candidates = list(self._scope_cache.values())
        if self.parent is None:
            for provider in self._providers.values():
                candidates.extend(cached_instances(provider))
        return self._tracker.ordered(candidates)

    def _detach_shutdown_instances(self) -> tuple[Any, ...]:
        candidates = list(self._shutdown_instances())
        self._scope_cache.clear()
        with self._scope_lock:
            self._scope_initializers.clear()
        if self.parent is None:
            for provider in self._providers.values():
                provider.instance = MISSING
                provider.singleton = MISSING
        ordered = self._tracker.ordered(candidates)
        self._tracker.forget(ordered)
        return ordered


class BaseDependencyContainer:
    """Base class for application-specific dependency registrations."""

    __slots__ = ("container",)

    def __init__(
        self,
        *,
        container: DependencyContainer | None = None,
        parent: DependencyContainer | None = None,
        set_as_default: bool = True,
        auto_wire: bool = True,
    ) -> None:
        self.container = container or DependencyContainer(
            parent=parent, auto_wire=auto_wire
        )
        self.configure()
        if set_as_default:
            set_default_container(self.container)

    def configure(self) -> None:
        """Override in a subclass to register application services."""

    def singleton(
        self,
        token: Token | None = None,
        provider: Any = MISSING,
        *,
        abstract: Token | None = None,
        concrete: Any = MISSING,
        factory: Any = MISSING,
        instance: Any = MISSING,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.container.singleton(
            token,
            provider,
            abstract=abstract,
            concrete=concrete,
            factory=factory,
            instance=instance,
            dependencies=dependencies,
            priority=priority,
        )

    def transient(
        self,
        token: Token | None = None,
        provider: Any = MISSING,
        *,
        abstract: Token | None = None,
        concrete: Any = MISSING,
        factory: Any = MISSING,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.container.transient(
            token,
            provider,
            abstract=abstract,
            concrete=concrete,
            factory=factory,
            dependencies=dependencies,
            priority=priority,
        )

    def scoped(
        self,
        token: Token | None = None,
        provider: Any = MISSING,
        *,
        abstract: Token | None = None,
        concrete: Any = MISSING,
        factory: Any = MISSING,
        dependencies: DependencyMap | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.container.scoped(
            token,
            provider,
            abstract=abstract,
            concrete=concrete,
            factory=factory,
            dependencies=dependencies,
            priority=priority,
        )

    def instance(
        self,
        token: Token | None = None,
        instance: Any = MISSING,
        *,
        abstract: Token | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> DependencyContainer:
        return self.container.instance(
            token,
            instance,
            abstract=abstract,
            priority=priority,
        )

    def inject(
        self,
        target: Callable[..., T] | type[T] | None = None,
        *,
        dependencies: DependencyMap | None = None,
        strict: bool = False,
        **named_dependencies: Token,
    ) -> Callable[..., T] | type[T] | Callable[[Callable[..., T] | type[T]], Any]:
        return self.container.inject(
            target,
            dependencies=dependencies,
            strict=strict,
            **named_dependencies,
        )

    def resolve(self, token: Token) -> Any:
        return self.container.resolve(token)

    async def resolve_async(self, token: Token) -> Any:
        return await self.container.resolve_async(token)

    def warmup(
        self,
        tokens: Iterable[Token] | None = None,
        *,
        lifetimes: Iterable[Lifetime | str] = (Lifetime.SINGLETON,),
    ) -> None:
        self.container.warmup(tokens=tokens, lifetimes=lifetimes)

    async def warmup_async(
        self,
        tokens: Iterable[Token] | None = None,
        *,
        lifetimes: Iterable[Lifetime | str] = (Lifetime.SINGLETON,),
    ) -> None:
        await self.container.warmup_async(tokens=tokens, lifetimes=lifetimes)

    def create_scope(self) -> DependencyContainer:
        return self.container.create_scope()

    def unregister(self, token: Token) -> None:
        self.container.unregister(token)

    async def unregister_async(self, token: Token) -> None:
        await self.container.unregister_async(token)

    def shutdown(self) -> None:
        self.container.shutdown()

    async def shutdown_async(self) -> None:
        await self.container.shutdown_async()


def set_default_container(container: DependencyContainer) -> None:
    global _default_container
    _default_container = container


def get_default_container() -> DependencyContainer:
    global _default_container
    if _default_container is None:
        _default_container = DependencyContainer()
    return _default_container


def get_current_container() -> DependencyContainer:
    return _current_container.get() or get_default_container()
