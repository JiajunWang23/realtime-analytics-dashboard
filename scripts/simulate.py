"""Synthetic event producer.

  python scripts/simulate.py --rate 1.2            # ~100K events/day (100_000 / 86_400 ≈ 1.16/s)
  python scripts/simulate.py --rate 50 --batch 10  # demo / load mode
"""
import argparse
import asyncio
import random
import time

import aiohttp

TYPES = [("page_view", 0.58), ("click", 0.24), ("add_to_cart", 0.07),
         ("purchase", 0.04), ("signup", 0.02), ("error", 0.05)]
PAGES = ["/", "/pricing", "/docs", "/blog", "/checkout", "/settings"]


def make_event(n_users: int) -> dict:
    t = random.choices([t for t, _ in TYPES], [w for _, w in TYPES])[0]
    value = round(random.lognormvariate(3.3, 0.6), 2) if t == "purchase" else (
        1.0 if t != "error" else 0.0)
    return {"type": t, "user_id": f"u{int(random.paretovariate(1.2)) % n_users}",
            "value": value, "props": {"path": random.choice(PAGES)},
            "ts": int(time.time() * 1000)}


async def main(a):
    interval = a.batch / a.rate
    sent = 0
    t0 = time.time()
    async with aiohttp.ClientSession() as s:
        while a.total == 0 or sent < a.total:
            batch = [make_event(a.users) for _ in range(a.batch)]
            try:
                async with s.post(f"{a.url}/api/events", json={"events": batch}) as resp:
                    if resp.status != 202:
                        print("error", resp.status, await resp.text())
            except aiohttp.ClientError as exc:
                print("post failed:", exc)
            sent += len(batch)
            if sent % max(a.batch, 500) < a.batch:
                print(f"sent={sent} rate={sent / (time.time() - t0):.1f}/s")
            # jitter so the stream looks bursty, not metronomic
            await asyncio.sleep(random.expovariate(1 / interval))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:5000")
    p.add_argument("--rate", type=float, default=1.2, help="events/second")
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--users", type=int, default=5000)
    p.add_argument("--total", type=int, default=0, help="stop after N events (0 = forever)")
    asyncio.run(main(p.parse_args()))
