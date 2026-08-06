from __future__ import annotations

import unittest
from typing import Annotated

from src.core.dependency import (
    AsyncDependencyError,
    DependencyContainer,
    DependencyNotFoundError,
    Inject,
    Lifetime,
)


class _Engine:
    pass


class _Vehicle:
    def __init__(self, engine: _Engine) -> None:
        self.engine = engine


class _AsyncClient:
    pass


class DependencyInjectionTests(unittest.TestCase):
    def test_autowire_and_explicit_annotation_injection(self) -> None:
        container = DependencyContainer()
        container.singleton(_Engine)
        vehicle = container.resolve(_Vehicle)
        self.assertIs(vehicle.engine, container.resolve(_Engine))

        @container.inject
        def use_engine(engine: Annotated[_Engine, Inject()]) -> _Engine:
            return engine

        self.assertIs(use_engine(), container.resolve(_Engine))

    def test_user_argument_is_not_overwritten_and_optional_can_be_none(self) -> None:
        class Service:
            pass

        container = DependencyContainer(auto_wire=False)

        @container.inject
        def call(
            service: Service = Inject(optional=True),
        ) -> Service | None:
            return service

        supplied = Service()
        self.assertIs(call(supplied), supplied)
        self.assertIsNone(call())

    def test_strict_injection_reports_missing_dependency(self) -> None:
        class Service:
            pass

        container = DependencyContainer(auto_wire=False)

        @container.inject(strict=True)
        def call(service: Service) -> Service:
            return service

        with self.assertRaises(DependencyNotFoundError):
            call()

    def test_provider_decorator_infers_return_token_and_warmup_priority(self) -> None:
        order: list[str] = []
        container = DependencyContainer()

        @container.provider(lifetime=Lifetime.SINGLETON, priority=20)
        def second() -> bytes:
            order.append("second")
            return b"second"

        @container.provider(lifetime=Lifetime.SINGLETON, priority=10)
        def first() -> str:
            order.append("first")
            return "first"

        container.warmup()
        self.assertEqual(order, ["first", "second"])
        self.assertEqual(container.resolve(str), "first")

    def test_sync_resolution_rejects_async_provider(self) -> None:
        async def factory() -> str:
            return "async"

        container = DependencyContainer()
        container.singleton(str, factory=factory)
        with self.assertRaises(AsyncDependencyError):
            container.resolve(str)


class AsyncDependencyInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_provider_and_decorated_callable(self) -> None:
        async def factory() -> _AsyncClient:
            return _AsyncClient()

        container = DependencyContainer()
        container.singleton(_AsyncClient, factory=factory)

        @container.inject
        async def use_client(client: _AsyncClient) -> _AsyncClient:
            return client

        first = await use_client()
        second = await container.resolve_async(_AsyncClient)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
