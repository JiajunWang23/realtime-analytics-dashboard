"""Wikimedia EventStreams -> analytics ingest.

Consumes the public `mediawiki.recentchange` Server-Sent-Events stream (every edit, page
creation, log action and category change across all Wikimedia wikis, ~30 events/s,
~2.5M/day) and forwards it in batches to POST /api/events with source="wikipedia".

  python connectors/wikipedia.py                                  # live stream
  python connectors/wikipedia.py --replay connectors/fixtures/wikimedia_recentchange_sample.jsonl --rate 30

Reliability:
  * resumes with Last-Event-ID after a disconnect, so no gap in the stream
  * exponential back-off (honours the server's `retry:` hint)
  * bounded in-memory buffer; if the backend is down the oldest events are dropped and counted
"""
import argparse
import asyncio
import json
import logging
import random
import ssl
import time
from collections import deque
from pathlib import Path

import aiohttp

STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"
# Wikimedia's User-Agent policy asks clients to identify themselves.
USER_AGENT = "RealTimeAnalyticsDashboard/1.0 (https://uiucwangjiajun.com) aiohttp"
log = logging.getLogger("wikipedia")


def ssl_context() -> ssl.SSLContext:
    """Prefer certifi's CA bundle: standalone Python builds (uv, pyenv) may not see the OS store."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def to_event(rc: dict) -> dict | None:
    """Map a recentchange record to the analytics event schema."""
    if rc.get("meta", {}).get("domain") == "canary":   # Wikimedia's synthetic health events
        return None
    length = rc.get("length") or {}
    delta = (length.get("new") or 0) - (length.get("old") or 0)
    etype = rc.get("type", "unknown")
    return {
        "source": "wikipedia",
        "type": etype,                                   # edit | new | log | categorize
        "user_id": (rc.get("user") or "anonymous")[:128],
        "value": abs(delta),                             # bytes changed
        "ts": rc.get("meta", {}).get("dt") or rc.get("timestamp"),
        "props": {
            "wiki": rc.get("wiki"),
            "bot": "bot" if rc.get("bot") else "human",
            "title": (rc.get("title") or "")[:200],
            "url": rc.get("title_url") or rc.get("meta", {}).get("uri"),
            "delta": delta,
            "ns": rc.get("namespace"),
            **({"log_type": rc["log_type"]} if rc.get("log_type") else {}),
        },
    }


class Forwarder:
    """Buffers events and POSTs them to the ingest API in batches."""

    def __init__(self, api: str, batch: int, flush_ms: int, max_buffer: int = 20_000):
        self.api = api.rstrip("/") + "/api/events"
        self.batch, self.flush_s = batch, flush_ms / 1000
        self.buf: deque = deque(maxlen=max_buffer)
        self.sent = self.dropped = self.received = 0

    def put(self, ev: dict):
        if len(self.buf) == self.buf.maxlen:
            self.dropped += 1
        self.buf.append(ev)
        self.received += 1

    async def run(self, session: aiohttp.ClientSession):
        backoff = 0.5
        while True:
            await asyncio.sleep(self.flush_s)
            while self.buf:
                chunk = [self.buf.popleft() for _ in range(min(self.batch, len(self.buf)))]
                try:
                    async with session.post(self.api, json={"events": chunk}) as resp:
                        if resp.status >= 500:
                            raise aiohttp.ClientResponseError(resp.request_info, (), status=resp.status)
                        if resp.status != 202:
                            log.warning("ingest rejected batch: %s %s", resp.status, await resp.text())
                    self.sent += len(chunk)
                    backoff = 0.5
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    log.warning("ingest unavailable (%s); retrying in %.1fs", exc, backoff)
                    self.buf.extendleft(reversed(chunk))      # put back, keep order
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 15)
                    break


async def consume_sse(url: str, fwd: Forwarder, session: aiohttp.ClientSession):
    last_id = None
    retry_s = 1.0
    attempt = 0
    while True:
        headers = {"Accept": "text/event-stream", "User-Agent": USER_AGENT}
        if last_id:
            headers["Last-Event-ID"] = last_id
        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_read=60)
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                resp.raise_for_status()
                log.info("connected to %s%s", url, f" (resuming after {last_id[:60]}...)" if last_id else "")
                attempt = 0
                data, ev_id = [], None
                async for raw in resp.content:                 # line by line
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if not line:                               # blank line = dispatch event
                        if data:
                            try:
                                ev = to_event(json.loads("\n".join(data)))
                                if ev:
                                    fwd.put(ev)
                            except ValueError:
                                pass
                            if ev_id is not None:
                                last_id = ev_id
                        data, ev_id = [], None
                    elif line.startswith(":"):
                        continue                               # comment / heartbeat
                    else:
                        field, _, value = line.partition(":")
                        value = value[1:] if value.startswith(" ") else value
                        if field == "data":
                            data.append(value)
                        elif field == "id":
                            ev_id = value
                        elif field == "retry" and value.isdigit():
                            retry_s = int(value) / 1000
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("stream error: %s", exc)
        attempt += 1
        delay = min(retry_s * 2 ** (attempt - 1), 30) * (0.5 + random.random())
        log.info("reconnecting in %.1fs", delay)
        await asyncio.sleep(delay)


async def replay(path: str, rate: float, fwd: Forwarder):
    """Offline mode: replay a recorded sample at `rate` events/s with fresh timestamps."""
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    log.info("replaying %d recorded events at %.0f/s", len(records), rate)
    i = 0
    while True:
        rc = dict(records[i % len(records)])
        rc["meta"] = {**rc.get("meta", {}), "dt": None}
        rc["timestamp"] = time.time()
        ev = to_event(rc)
        if ev:
            fwd.put(ev)
        i += 1
        await asyncio.sleep(random.expovariate(rate))


async def report(fwd: Forwarder, every: int = 10):
    t0, last = time.time(), 0
    while True:
        await asyncio.sleep(every)
        log.info("received=%d sent=%d buffered=%d dropped=%d  (%.1f ev/s)",
                 fwd.received, fwd.sent, len(fwd.buf), fwd.dropped, (fwd.sent - last) / every)
        last = fwd.sent


async def main(a):
    fwd = Forwarder(a.api, a.batch, a.flush_ms)
    connector = aiohttp.TCPConnector(ssl=ssl_context())
    async with aiohttp.ClientSession(connector=connector) as session:
        producer = replay(a.replay, a.rate, fwd) if a.replay else consume_sse(a.url, fwd, session)
        await asyncio.gather(producer, fwd.run(session), report(fwd))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:5000")
    p.add_argument("--url", default=STREAM_URL)
    p.add_argument("--batch", type=int, default=200)
    p.add_argument("--flush-ms", type=int, default=250)
    p.add_argument("--replay", help="JSONL of recorded recentchange events (offline mode)")
    p.add_argument("--rate", type=float, default=30, help="replay rate, events/s")
    asyncio.run(main(p.parse_args()))
