from __future__ import annotations

import asyncio
import threading
import unittest

from src.core.dependency import DependencyContainer


class ShutdownCoordinationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_caller_waits_for_async_owned_shutdown(self) -> None:
        entered = threading.Event()
        release = asyncio.Event()

        class Resource:
            async def aclose(self) -> None:
                entered.set()
                await release.wait()

        container = DependencyContainer()
        container.instance(Resource, Resource())
        owner = asyncio.create_task(container.shutdown_async())
        self.assertTrue(await asyncio.to_thread(entered.wait, 1.0))
        waiter = asyncio.create_task(asyncio.to_thread(container.shutdown))
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        release.set()
        await asyncio.gather(owner, waiter)
        self.assertTrue(container.closed)

    async def test_async_caller_waits_for_sync_owned_shutdown(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        class Resource:
            def close(self) -> None:
                entered.set()
                release.wait(1.0)

        container = DependencyContainer()
        container.instance(Resource, Resource())
        thread = threading.Thread(target=container.shutdown)
        thread.start()
        self.assertTrue(await asyncio.to_thread(entered.wait, 1.0))
        waiter = asyncio.create_task(container.shutdown_async())
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        release.set()
        await waiter
        thread.join(1.0)
        self.assertFalse(thread.is_alive())
        self.assertTrue(container.closed)


if __name__ == "__main__":
    unittest.main()
