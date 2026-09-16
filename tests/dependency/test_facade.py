from __future__ import annotations

import unittest

from src.core.dependency import (
    BaseDependencyContainer,
    DependencyContainer,
    DependencyNotFoundError,
    Lifetime,
    get_default_container,
)


class _ApplicationContainer(BaseDependencyContainer):
    def configure(self) -> None:
        self.singleton(str, instance="configured")


class DependencyFacadeTests(unittest.IsolatedAsyncioTestCase):
    def test_configure_and_sync_forwarders_keep_container_ownership(self) -> None:
        application = _ApplicationContainer(set_as_default=False, auto_wire=False)

        self.assertEqual(application.resolve(str), "configured")
        self.assertIsNot(application.container, get_default_container())

        application.transient(bytes, factory=lambda: b"value")
        application.scoped(list, factory=list)
        application.instance(int, 7)
        application.warmup(lifetimes=(Lifetime.SINGLETON,))

        self.assertEqual(application.resolve(bytes), b"value")
        self.assertEqual(application.resolve(int), 7)
        scope = application.create_scope()
        self.assertIs(scope.resolve(list), scope.resolve(list))
        application.unregister(int)
        with self.assertRaises(DependencyNotFoundError):
            application.resolve(int)

        scope.shutdown()
        application.shutdown()
        self.assertTrue(application.container.closed)

    async def test_async_forwarders_and_injection_delegate_without_wrapping(self) -> None:
        application = BaseDependencyContainer(
            container=DependencyContainer(auto_wire=False),
            set_as_default=False,
        )
        application.singleton(str, instance="async")

        @application.inject
        async def read(value: str) -> str:
            return value

        self.assertEqual(await application.resolve_async(str), "async")
        self.assertEqual(await read(), "async")
        await application.warmup_async()
        await application.unregister_async(str)
        with self.assertRaises(DependencyNotFoundError):
            await application.resolve_async(str)
        await application.shutdown_async()
