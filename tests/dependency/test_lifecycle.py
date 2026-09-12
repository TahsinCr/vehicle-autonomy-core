from __future__ import annotations

import unittest
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from src.core.dependency import (
    AsyncDependencyError,
    DependencyCleanupPendingError,
    DependencyContainer,
    DependencyContainerClosedError,
    get_current_container,
    set_default_container,
)
from src.core.dependency.registration import InitializationGate
from src.core.compatibility import ExceptionGroup


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
    def test_concurrent_shutdown_disposes_a_resource_once(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        class Resource:
            calls = 0

            def close(self) -> None:
                self.calls += 1
                entered.set()
                release.wait(1.0)

        resource = Resource()
        container = DependencyContainer()
        container.instance("resource", resource)
        first = threading.Thread(target=container.shutdown)
        second_done = threading.Event()
        second = threading.Thread(
            target=lambda: (container.shutdown(), second_done.set())
        )
        first.start()
        self.assertTrue(entered.wait(1.0))
        second.start()
        self.assertFalse(second_done.wait(0.02))
        release.set()
        first.join(1.0)
        second.join(1.0)
        self.assertFalse(second.is_alive())
        self.assertTrue(second_done.is_set())
        self.assertEqual(resource.calls, 1)

    def test_concurrent_shutdown_callers_receive_the_same_failure(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        class Resource:
            fail = True

            def close(self) -> None:
                entered.set()
                release.wait(1.0)
                if self.fail:
                    raise RuntimeError("cleanup failed")

        resource = Resource()
        container = DependencyContainer()
        container.instance("resource", resource)
        errors: list[str] = []

        def shutdown() -> None:
            try:
                container.shutdown()
            except RuntimeError as error:
                errors.append(str(error))

        first = threading.Thread(target=shutdown)
        second = threading.Thread(target=shutdown)
        first.start()
        self.assertTrue(entered.wait(1.0))
        second.start()
        release.set()
        first.join(1.0)
        second.join(1.0)
        self.assertEqual(errors, ["cleanup failed", "cleanup failed"])

        resource.fail = False
        container.shutdown()
        self.assertTrue(container.closed)

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

    def test_scope_shutdown_closes_resources_registered_on_that_scope(self) -> None:
        resource = _SyncResource("local", [])
        scope = DependencyContainer().create_scope()
        scope.instance("local", resource)

        scope.shutdown()

        self.assertEqual(resource.close_count, 1)

    def test_unregister_waits_for_inflight_singleton_and_closes_it(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        resource = _SyncResource("inflight", [])

        def factory() -> _SyncResource:
            entered.set()
            self.assertTrue(release.wait(1.0))
            return resource

        container = DependencyContainer()
        container.singleton("resource", factory=factory)
        resolver = threading.Thread(target=container.resolve, args=("resource",))
        resolver.start()
        self.assertTrue(entered.wait(1.0))

        unregister_done = threading.Event()
        unregister = threading.Thread(
            target=lambda: (container.unregister("resource"), unregister_done.set())
        )
        unregister.start()
        self.assertFalse(unregister_done.wait(0.02))
        release.set()
        resolver.join(1.0)
        unregister.join(1.0)

        self.assertTrue(unregister_done.is_set())
        self.assertEqual(resource.close_count, 1)
        self.assertFalse(container.has("resource"))

    def test_sync_wait_rejects_async_initializer_on_same_thread(self) -> None:
        gate = InitializationGate()
        self.assertTrue(gate.claim(asynchronous=True))
        with self.assertRaisesRegex(RuntimeError, "event-loop thread"):
            gate.wait()
        gate.release()

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
        first.fail = False
        second.fail = False
        container.shutdown()
        self.assertEqual([first.close_count, second.close_count, third.close_count], [2, 2, 1])

    def test_failed_unregister_disposal_remains_owned_for_retry(self) -> None:
        resource = _SyncResource("retry", [], fail=True)
        container = DependencyContainer()
        container.instance("resource", resource)

        with self.assertRaisesRegex(RuntimeError, "cannot close retry"):
            container.unregister("resource")
        self.assertFalse(container.has("resource"))
        with self.assertRaises(DependencyCleanupPendingError):
            container.instance("resource", object())

        resource.fail = False
        container.unregister("resource")
        self.assertEqual(resource.close_count, 2)

    def test_successful_shutdown_is_terminal_for_all_lifetimes(self) -> None:
        container = DependencyContainer()
        container.transient("transient", object)
        container.scoped("scoped", object)
        container.singleton("singleton", object)
        container.resolve("singleton")
        container.shutdown()

        self.assertTrue(container.closed)
        for token in ("transient", "scoped", "singleton"):
            with self.assertRaises(DependencyContainerClosedError):
                container.resolve(token)
        with self.assertRaises(DependencyContainerClosedError):
            container.instance("new", object())

    def test_scoped_resolution_is_singleton_per_scope_across_threads(self) -> None:
        created = 0
        lock = threading.Lock()

        def factory() -> object:
            nonlocal created
            time.sleep(0.01)
            with lock:
                created += 1
            return object()

        root = DependencyContainer()
        root.scoped("resource", factory=factory)
        scope = root.create_scope()
        with ThreadPoolExecutor(max_workers=8) as executor:
            instances = tuple(executor.map(lambda _index: scope.resolve("resource"), range(16)))

        self.assertEqual(created, 1)
        self.assertTrue(all(item is instances[0] for item in instances))

    def test_shared_instance_is_disposed_after_last_token_is_removed(self) -> None:
        resource = _SyncResource("shared", [])
        container = DependencyContainer()
        container.instance("interface", resource)
        container.instance("concrete", resource)

        container.unregister("interface")
        self.assertEqual(resource.close_count, 0)
        self.assertIs(container.resolve("concrete"), resource)

        container.unregister("concrete")
        self.assertEqual(resource.close_count, 1)


    def test_cross_thread_initialization_cycle_fails_instead_of_deadlocking(self) -> None:
        container = DependencyContainer()
        barrier = threading.Barrier(2)
        calls = {"a": 0, "b": 0}
        calls_lock = threading.Lock()

        def synchronize(name: str) -> None:
            with calls_lock:
                calls[name] += 1
                first = calls[name] == 1
            if first:
                barrier.wait()

        def build_a():
            synchronize("a")
            return container.resolve("b")

        def build_b():
            synchronize("b")
            return container.resolve("a")

        container.singleton("a", factory=build_a)
        container.singleton("b", factory=build_b)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(container.resolve, "a"), executor.submit(container.resolve, "b"))
            errors = []
            for future in futures:
                with self.assertRaises(Exception) as caught:
                    future.result(timeout=1.0)
                errors.append(caught.exception)
        self.assertTrue(any("cycle" in str(error).lower() for error in errors))


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

    async def test_failed_async_unregister_reserves_token_until_retry(self) -> None:
        resource = _AsyncResource("async", [], fail=True)
        container = DependencyContainer()
        container.instance("resource", resource)

        with self.assertRaisesRegex(RuntimeError, "cannot close async"):
            await container.unregister_async("resource")
        with self.assertRaises(DependencyCleanupPendingError):
            container.instance("resource", object())

        resource.fail = False
        await container.unregister_async("resource")
        self.assertEqual(resource.close_count, 2)

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
        first.fail = False
        second.fail = False
        await container.shutdown_async()
        self.assertEqual([first.close_count, second.close_count, third.close_count], [2, 2, 1])

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

    async def test_concurrent_async_scoped_resolution_creates_once(self) -> None:
        created = 0

        async def factory() -> object:
            nonlocal created
            await asyncio.sleep(0.01)
            created += 1
            return object()

        root = DependencyContainer()
        root.scoped("resource", factory=factory)
        scope = root.create_scope()
        instances = await asyncio.gather(
            *(scope.resolve_async("resource") for _ in range(16))
        )

        self.assertEqual(created, 1)
        self.assertTrue(all(item is instances[0] for item in instances))

    async def test_cross_task_cached_provider_cycle_is_detected(self) -> None:
        container = DependencyContainer()
        a_started = asyncio.Event()
        b_started = asyncio.Event()

        async def build_a() -> object:
            a_started.set()
            await b_started.wait()
            return await container.resolve_async("b")

        async def build_b() -> object:
            b_started.set()
            await a_started.wait()
            return await container.resolve_async("a")

        container.singleton("a", factory=build_a)
        container.singleton("b", factory=build_b)
        results = await asyncio.wait_for(
            asyncio.gather(
                container.resolve_async("a"),
                container.resolve_async("b"),
                return_exceptions=True,
            ),
            1.0,
        )
        self.assertTrue(all(isinstance(result, Exception) for result in results))
        self.assertTrue(any("cycle" in str(result).lower() for result in results))

    async def test_child_tasks_share_one_cached_dependency_without_false_cycle(self) -> None:
        container = DependencyContainer()

        async def build_shared() -> object:
            await asyncio.sleep(0)
            return object()

        async def build_parent() -> tuple[object, object]:
            first, second = await asyncio.gather(
                container.resolve_async("shared"),
                container.resolve_async("shared"),
            )
            return first, second

        container.singleton("shared", factory=build_shared)
        container.singleton("parent", factory=build_parent)
        first, second = await container.resolve_async("parent")
        self.assertIs(first, second)

    async def test_dynamic_awaitable_close_can_be_retried_asynchronously(self) -> None:
        class DynamicResource:
            def __init__(self) -> None:
                self.close_calls = 0
                self.cleaned = 0

            def close(self):
                self.close_calls += 1

                async def cleanup() -> None:
                    self.cleaned += 1

                return cleanup()

        resource = DynamicResource()
        container = DependencyContainer()
        container.instance("resource", resource)

        with self.assertRaises(AsyncDependencyError):
            container.unregister("resource")
        await container.shutdown_async()
        self.assertEqual((resource.close_calls, resource.cleaned), (2, 1))

    async def test_sync_and_async_resolution_share_one_cached_initialization(self) -> None:
        for lifetime in ("singleton", "scoped"):
            with self.subTest(lifetime=lifetime):
                started = threading.Event()
                release = threading.Event()
                created = 0

                def factory() -> object:
                    nonlocal created
                    started.set()
                    release.wait(1.0)
                    created += 1
                    return object()

                root = DependencyContainer()
                getattr(root, lifetime)("resource", factory=factory)
                container = root if lifetime == "singleton" else root.create_scope()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    sync_future = executor.submit(container.resolve, "resource")
                    self.assertTrue(await asyncio.to_thread(started.wait, 1.0))
                    async_task = asyncio.create_task(
                        container.resolve_async("resource")
                    )
                    await asyncio.sleep(0.01)
                    self.assertFalse(async_task.done())
                    release.set()
                    sync_value = await asyncio.wrap_future(sync_future)
                    async_value = await async_task

                self.assertIs(sync_value, async_value)
                self.assertEqual(created, 1)

    async def test_sync_resolution_waits_for_async_singleton_initialization(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        created = 0

        async def factory() -> object:
            nonlocal created
            started.set()
            await release.wait()
            created += 1
            return object()

        container = DependencyContainer()
        container.singleton("resource", factory=factory)
        async_task = asyncio.create_task(container.resolve_async("resource"))
        await asyncio.wait_for(started.wait(), 1.0)

        with ThreadPoolExecutor(max_workers=1) as executor:
            sync_future = executor.submit(container.resolve, "resource")
            await asyncio.sleep(0.01)
            self.assertFalse(sync_future.done())
            release.set()
            async_value = await async_task
            sync_value = await asyncio.wrap_future(sync_future)

        self.assertIs(sync_value, async_value)
        self.assertEqual(created, 1)

    async def test_sync_shutdown_keeps_async_resources_attached(self) -> None:
        resource = _AsyncResource("async", [])
        container = DependencyContainer()
        container.instance("resource", resource)

        with self.assertRaises(AsyncDependencyError):
            container.shutdown()

        self.assertIs(container.resolve("resource"), resource)
        await container.shutdown_async()
        self.assertEqual(resource.close_count, 1)

    async def test_cancelled_shutdown_still_attempts_remaining_resources(self) -> None:
        entered = asyncio.Event()

        class _SlowResource:
            async def aclose(inner_self) -> None:
                entered.set()
                await asyncio.Event().wait()

        closed: list[str] = []
        container = DependencyContainer()
        container.instance("remaining", _AsyncResource("remaining", closed))
        container.instance("slow", _SlowResource())

        shutdown = asyncio.create_task(container.shutdown_async())
        await asyncio.wait_for(entered.wait(), 1.0)
        shutdown.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(shutdown, 1.0)

        self.assertEqual(closed, ["remaining"])

    async def test_cancelled_unregister_cleans_inflight_resource(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        closed: list[str] = []

        async def factory() -> _AsyncResource:
            started.set()
            await release.wait()
            return _AsyncResource("inflight", closed)

        container = DependencyContainer()
        container.singleton("resource", factory=factory)
        resolution = asyncio.create_task(container.resolve_async("resource"))
        await asyncio.wait_for(started.wait(), 1.0)
        unregister = asyncio.create_task(container.unregister_async("resource"))
        await asyncio.sleep(0)
        unregister.cancel()
        release.set()

        await resolution
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(unregister, 1.0)
        self.assertEqual(closed, ["inflight"])
        self.assertFalse(container.has("resource"))


if __name__ == "__main__":
    unittest.main()
