"""Per-pod fan-out hub.

One Redis SUBSCRIBE per worker process (not per client): Redis pub/sub delivers every
ingested batch to every pod, and each pod fans it out to its own WebSocket clients.
This is what lets the WebSocket tier scale horizontally behind a plain load balancer.

  ingest (any pod) --PUBLISH--> Redis channel --> listener (each pod) --> inbox
  flusher: coalesce inbox for BROADCAST_WINDOW_MS -> serialize once -> client queues
"""
import json
import logging
import os
import queue
import socket
import threading
import time

from .metrics import WS_CLIENTS
from .redis_client import r
from . import stats

log = logging.getLogger(__name__)
POD = f"{socket.gethostname()}:{os.getpid()}"


class Client:
    __slots__ = ("q", "dropped")

    def __init__(self, maxsize=256):
        self.q: queue.Queue = queue.Queue(maxsize=maxsize)
        self.dropped = 0

    def offer(self, frame: str):
        try:
            self.q.put_nowait(frame)
        except queue.Full:  # slow consumer: drop instead of blocking everyone
            self.dropped += 1


class Hub:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clients: set[Client] = set()
        self.lock = threading.Lock()
        self.inbox: queue.Queue = queue.Queue(maxsize=10000)
        self.started = False

    # ---- client registry -------------------------------------------------
    def register(self) -> Client:
        c = Client()
        with self.lock:
            self.clients.add(c)
            WS_CLIENTS.set(len(self.clients))
        return c

    def unregister(self, c: Client):
        with self.lock:
            self.clients.discard(c)
            WS_CLIENTS.set(len(self.clients))

    def broadcast(self, frame: str):
        with self.lock:
            targets = list(self.clients)
        for c in targets:
            c.offer(frame)

    # ---- background loops --------------------------------------------------
    def start(self):
        if self.started:
            return
        self.started = True
        for fn in (self._listen, self._flush, self._stats_tick):
            threading.Thread(target=fn, daemon=True, name=fn.__name__).start()

    def _listen(self):
        while True:
            try:
                ps = r().pubsub(ignore_subscribe_messages=True)
                ps.subscribe(self.cfg.EVENTS_CHANNEL)
                log.info("subscribed to %s", self.cfg.EVENTS_CHANNEL)
                for msg in ps.listen():
                    if msg and msg.get("type") == "message":
                        try:
                            self.inbox.put_nowait(msg["data"])
                        except queue.Full:
                            pass
            except Exception as exc:  # Redis restart / network blip -> resubscribe
                log.warning("pubsub error %s, resubscribing", exc)
                time.sleep(1)

    def _flush(self):
        window = self.cfg.BROADCAST_WINDOW_MS / 1000
        while True:
            first = self.inbox.get()
            batch = [first]
            deadline = time.monotonic() + window
            while (left := deadline - time.monotonic()) > 0:
                try:
                    batch.append(self.inbox.get(timeout=left))
                except queue.Empty:
                    break
            events = []
            for raw in batch:
                try:
                    events.extend(json.loads(raw).get("events", []))
                except ValueError:
                    continue
            if events and self.clients:
                self.broadcast(json.dumps({"kind": "events", "events": events,
                                           "sent_at": int(time.time() * 1000)}))

    def _stats_tick(self):
        while True:
            time.sleep(1)
            try:
                # heartbeat key per worker; dead pods age out after 5s
                r().set(f"ws:clients:{POD}", len(self.clients), ex=5)
                if self.clients:
                    self.broadcast(json.dumps({"kind": "stats", **stats.live_summary()}))
            except Exception as exc:
                log.warning("stats tick failed: %s", exc)
