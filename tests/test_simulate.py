"""Regression tests for simulator batch limits; no HTTP requests are sent."""
import io
import unittest
from contextlib import redirect_stdout
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from scripts import simulate


class StopSimulation(Exception):
    """Stop unlimited mode after a controlled number of batches."""


class SimulateTests(unittest.IsolatedAsyncioTestCase):
    async def batch_sizes(self, total, batch_size, stop_after=None):
        args = SimpleNamespace(
            url="http://example.invalid", rate=1000, batch=batch_size,
            total=total, users=10,
        )
        session = MagicMock()
        session.__aenter__.return_value = session
        session.post.return_value.__aenter__.return_value = MagicMock(status=202)
        sleep = AsyncMock()
        if stop_after is not None:
            sleep.side_effect = [None] * (stop_after - 1) + [StopSimulation()]

        with (
            patch.object(simulate.aiohttp, "ClientSession", return_value=session),
            patch.object(simulate.asyncio, "sleep", sleep),
            patch.object(simulate.time, "time", side_effect=count(1)),
            patch.object(simulate, "make_event", return_value={
                "type": "page_view", "user_id": "test-user",
            }) as make_event,
            redirect_stdout(io.StringIO()),
        ):
            if stop_after is None:
                await simulate.main(args)
            else:
                with self.assertRaises(StopSimulation):
                    await simulate.main(args)

        sizes = []
        for call in session.post.call_args_list:
            self.assertEqual(call.args, ("http://example.invalid/api/events",))
            sizes.append(len(call.kwargs["json"]["events"]))
        self.assertEqual(make_event.call_count, sum(sizes))
        return sizes

    async def test_partial_final_batch(self):
        self.assertEqual(await self.batch_sizes(105, 100), [100, 5])

    async def test_total_smaller_than_batch(self):
        self.assertEqual(await self.batch_sizes(5, 100), [5])

    async def test_total_divisible_by_batch(self):
        self.assertEqual(await self.batch_sizes(200, 100), [100, 100])

    async def test_single_event(self):
        self.assertEqual(await self.batch_sizes(1, 1), [1])

    async def test_zero_total_keeps_sending_full_batches(self):
        self.assertEqual(await self.batch_sizes(0, 100, stop_after=3), [100, 100, 100])


if __name__ == "__main__":
    unittest.main()
