from __future__ import annotations

import unittest

from src.core.dependency import (
    AsyncDependencyError,
    DependencyContainer,
    get_current_container,
    set_default_container,
)


class _SyncResource:
    def __init__(
        self,
        name: str,
        closed: list[str],
        *,
        fail: bool = False,
    ) -> None:
        self.name = name
        self.closed = closed
        self.fail = fail
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        self.closed.append(self.name)
        if self.fail:
            raise RuntimeError(f"cannot close {self.name}")


class _AsyncResource:
    def __init__(
        self,
        name: str,
        closed: list[str],
        *,
        fail: bool = False,
    ) -> None:
        self.name = name
        self.closed = closed
        self.fail = fail
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1
        self.closed.append(self.name)
        if self.fail:
            raise RuntimeError(f"cannot close {self.name}")


class DependencyLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.default = DependencyContainer()
        set_default_container(self.default)

    def tearDown(self) -> None:
        set_default_container(DependencyContainer())

    def test_context_is_reset_when_sync_shutdown_fails(self) -> None:
        container = DependencyContainer()
        container.instance("broken", _SyncResource("broken", [], fail=True))

        with self.assertRaisesRegex(RuntimeError, "cannot close broken"):
            with container:
                self.assertIs(get_current_container(), container)

        self.assertIs(get_current_container(), self.default)

    def test_unregister_closes_resource_once(self) -> None:
        closed: list[str] = []
        resource = _SyncResource("resource", closed)
        container = DependencyContainer()
        container.instance("resource", resource)

        container.unregister("resource")
        container.unregister("resource")
        container.shutdown()

        self.assertEqual(closed, ["resource"])
        self.assertEqual(resource.close_count, 1)

    def test_register_replacement_closes_previous_singleton(self) -> None:
        closed: list[str] = []
        previous = _SyncResource("previous", closed)
        current = _SyncResource("current", closed)
        container = DependencyContainer()
        container.instance("resource", previous)

        container.instance("resource", current)

        self.assertEqual(previous.close_count, 1)
        self.assertIs(container.resolve("resource"), current)
        container.shutdown()
        self.assertEqual(closed, ["previous", "current"])

    def test_unregister_closes_scoped_resource_owned_by_scope(self) -> None:
        closed: list[str] = []
        resource = _SyncResource("scoped", closed)
        root = DependencyContainer()
        root.scoped("resource", factory=lambda: resource)
        scope = root.create_scope()

        self.assertIs(scope.resolve("resource"), resource)
        scope.unregister("resource")
        scope.shutdown()

        self.assertEqual(closed, ["scoped"])
        self.assertEqual(resource.close_count, 1)

    def test_sync_unregister_rejects_async_only_cleanup_explicitly(self) -> None:
        resource = _AsyncResource("async", [])
        container = DependencyContainer()
        container.instance("resource", resource)

        with self.assertRaises(AsyncDependencyError):
            container.unregister("resource")

        self.assertEqual(resource.close_count, 0)
        self.assertIs(container.resolve("resource"), resource)

    def test_shutdown_attempts_every_resource_in_reverse_creation_order(self) -> None:
        closed: list[str] = []
        first = _SyncResource("first", closed, fail=True)
        second = _SyncResource("second", closed, fail=True)
        third = _SyncResource("third", closed)
        container = DependencyContainer()
        container.instance("first", first)
        container.instance("second", second)
        container.instance("third", third)

        with self.assertRaises(ExceptionGroup) as raised:
            container.shutdown()

        self.assertEqual(closed, ["third", "second", "first"])
        self.assertEqual(len(raised.exception.exceptions), 2)
        container.shutdown()
        self.assertEqual([first.close_count, second.close_count, third.close_count], [1, 1, 1])


class AsyncDependencyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.default = DependencyContainer()
        set_default_container(self.default)

    async def asyncTearDown(self) -> None:
        set_default_container(DependencyContainer())

    async def test_context_is_reset_when_async_shutdown_fails(self) -> None:
        container = DependencyContainer()
        container.instance("broken", _AsyncResource("broken", [], fail=True))

        with self.assertRaisesRegex(RuntimeError, "cannot close broken"):
            async with container:
                self.assertIs(get_current_container(), container)

        self.assertIs(get_current_container(), self.default)

    async def test_unregister_async_closes_resource_once(self) -> None:
        closed: list[str] = []
        resource = _AsyncResource("resource", closed)
        container = DependencyContainer()
        container.instance("resource", resource)

        await container.unregister_async("resource")
        await container.unregister_async("resource")
        await container.shutdown_async()

        self.assertEqual(closed, ["resource"])
        self.assertEqual(resource.close_count, 1)

    async def test_async_shutdown_aggregates_errors_and_continues(self) -> None:
        closed: list[str] = []
        first = _AsyncResource("first", closed, fail=True)
        second = _AsyncResource("second", closed, fail=True)
        third = _AsyncResource("third", closed)
        container = DependencyContainer()
        container.instance("first", first)
        container.instance("second", second)
        container.instance("third", third)

        with self.assertRaises(ExceptionGroup) as raised:
            await container.shutdown_async()

        self.assertEqual(closed, ["third", "second", "first"])
        self.assertEqual(len(raised.exception.exceptions), 2)
        await container.shutdown_async()
        self.assertEqual([first.close_count, second.close_count, third.close_count], [1, 1, 1])

    async def test_async_provider_and_scoped_cleanup(self) -> None:
        closed: list[str] = []
        created: list[_AsyncResource] = []

        async def factory() -> _AsyncResource:
            resource = _AsyncResource(f"scope-{len(created)}", closed)
            created.append(resource)
            return resource

        root = DependencyContainer()
        root.scoped("resource", factory=factory)
        first_scope = root.create_scope()
        second_scope = root.create_scope()

        first = await first_scope.resolve_async("resource")
        self.assertIs(first, await first_scope.resolve_async("resource"))
        second = await second_scope.resolve_async("resource")
        self.assertIsNot(first, second)

        await first_scope.shutdown_async()
        await second_scope.shutdown_async()
        self.assertEqual(closed, ["scope-0", "scope-1"])


if __name__ == "__main__":
    unittest.main()
