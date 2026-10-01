"""End-to-end latency + concurrency benchmark.

Opens N WebSocket clients, then POSTs tagged events one at a time. For every client we
record (time event frame arrived) - (time the POST was issued): that is the full path
HTTP ingest -> Postgres write -> Redis PUBLISH -> pod subscriber -> WebSocket frame.

  python scripts/bench_ws.py --clients 1 --events 300       # latency
  python scripts/bench_ws.py --clients 1000 --events 100    # 1K concurrent users
"""
import argparse
import asyncio
import json
import statistics
import time
import uuid

import aiohttp
import websockets

sent_at: dict[str, float] = {}
latencies: list[float] = []
received: dict[int, int] = {}


async def client(i: int, url: str, ready: asyncio.Event, stop: asyncio.Event, opened: list):
    async with websockets.connect(url, max_size=None, open_timeout=60, ping_interval=None) as ws:
        opened.append(i)
        received[i] = 0
        await ready.wait()
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            now = time.perf_counter()
            msg = json.loads(raw)
            if msg.get("kind") != "events":
                continue
            for e in msg["events"]:
                tag = e.get("props", {}).get("bench")
                if tag in sent_at:
                    latencies.append((now - sent_at[tag]) * 1000)
                    received[i] += 1


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p / 100))]


async def main(a):
    ready, stop, opened = asyncio.Event(), asyncio.Event(), []
    t0 = time.perf_counter()
    tasks = []
    for i in range(a.clients):
        tasks.append(asyncio.create_task(client(i, a.ws, ready, stop, opened)))
        if i % 100 == 99:
            await asyncio.sleep(0.05)  # don't SYN-flood the listener
    while len(opened) < a.clients:
        await asyncio.sleep(0.1)
        if time.perf_counter() - t0 > 120:
            break
    print(f"connected {len(opened)}/{a.clients} clients in {time.perf_counter() - t0:.1f}s")
    ready.set()
    await asyncio.sleep(1)

    async with aiohttp.ClientSession() as s:
        for _ in range(a.events):
            tag = uuid.uuid4().hex
            sent_at[tag] = time.perf_counter()
            async with s.post(f"{a.http}/api/events", json={
                    "type": "bench", "user_id": "bench", "props": {"bench": tag}}) as resp:
                assert resp.status == 202, await resp.text()
            await asyncio.sleep(a.interval)
    await asyncio.sleep(2)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    expected = a.events * len(opened)
    print(f"deliveries {len(latencies)}/{expected} "
          f"({100 * len(latencies) / max(expected, 1):.2f}%)")
    if latencies:
        print(f"latency ms  p50={pct(latencies, 50):.1f}  p95={pct(latencies, 95):.1f}  "
              f"p99={pct(latencies, 99):.1f}  mean={statistics.mean(latencies):.1f}  "
              f"max={max(latencies):.1f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--http", default="http://localhost:5000")
    p.add_argument("--ws", default="ws://localhost:5000/ws")
    p.add_argument("--clients", type=int, default=1)
    p.add_argument("--events", type=int, default=200)
    p.add_argument("--interval", type=float, default=0.05)
    asyncio.run(main(p.parse_args()))
