"""On-demand Wikipedia pull: the serverless counterpart of connectors/wikipedia.py.

Platforms like Vercel can't keep a process connected to the Wikimedia stream around the
clock, so while someone has the dashboard open the frontend calls /api/ingest/wikipedia
every ~20 s. Each call:

  * takes a Postgres advisory lock, so only one pull runs at a time however many viewers
    there are (other calls return immediately with status "busy");
  * resumes from the stored Last-Event-ID when the previous pull ended < 2 min ago (no gap
    between back-to-back pulls), otherwise starts from "now";
  * reads the SSE stream for N seconds, ingesting through the normal ingest path in
    ~1 s batches (Postgres raw + rollup, Redis if configured);
  * prunes raw Wikipedia rows older than WIKI_RETENTION_HOURS (rollups are kept).
"""
import json
import logging
import time

import psycopg2
import requests

from .ingest import ValidationError, ingest, validate

log = logging.getLogger(__name__)
LOCK_KEY = 7_770_001
USER_AGENT = "RealTimeAnalyticsDashboard/1.0 (https://uiucwangjiajun.com) python-requests"
RESUME_WINDOW_S = 120


def to_event(rc: dict) -> dict | None:
    """Same mapping as connectors/wikipedia.py."""
    if rc.get("meta", {}).get("domain") == "canary":
        return None
    length = rc.get("length") or {}
    delta = (length.get("new") or 0) - (length.get("old") or 0)
    return {
        "source": "wikipedia",
        "type": rc.get("type", "unknown"),
        "user_id": (rc.get("user") or "anonymous")[:128],
        "value": abs(delta),
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


def pull(cfg, seconds: int) -> dict:
    lock_conn = psycopg2.connect(cfg.DATABASE_URL)
    lock_conn.autocommit = True
    cur = lock_conn.cursor()
    try:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        if not cur.fetchone()[0]:
            return {"status": "busy"}
        cur.execute("""SELECT last_id FROM connector_state WHERE name = 'wikipedia'
                       AND updated_at > now() - make_interval(secs => %s)""", (RESUME_WINDOW_S,))
        row = cur.fetchone()
        last_id = row[0] if row else None
        result = _read_stream(cfg, cur, seconds, last_id)
        result["resumed"] = last_id is not None
        if cfg.WIKI_RETENTION_HOURS:
            cur.execute("""DELETE FROM events WHERE id IN (
                             SELECT id FROM events WHERE source = 'wikipedia'
                             AND occurred_at < now() - make_interval(hours => %s) LIMIT 20000)""",
                        (cfg.WIKI_RETENTION_HOURS,))
            result["pruned"] = cur.rowcount
        return result
    finally:
        try:
            cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        finally:
            lock_conn.close()


def _save_cursor(cur, last_id):
    cur.execute("""INSERT INTO connector_state (name, last_id, updated_at) VALUES ('wikipedia', %s, now())
                   ON CONFLICT (name) DO UPDATE SET last_id = EXCLUDED.last_id, updated_at = now()""",
                (last_id,))


def _read_stream(cfg, cur, seconds: int, last_id: str | None) -> dict:
    headers = {"Accept": "text/event-stream", "User-Agent": USER_AGENT}
    if last_id:
        headers["Last-Event-ID"] = last_id
    deadline = time.monotonic() + seconds
    batch, ingested, data, ev_id = [], 0, [], None
    last_flush = time.monotonic()

    def flush():
        nonlocal batch, ingested, last_flush
        if batch:
            ingested += ingest(batch, cfg.EVENTS_CHANNEL, cfg.DIM_KEYS)
            batch = []
        if last_id:
            _save_cursor(cur, last_id)
        last_flush = time.monotonic()

    with requests.get(cfg.WIKI_STREAM_URL, headers=headers, stream=True, timeout=(5, 15)) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(chunk_size=1024, decode_unicode=True):
            line = (raw or "").rstrip("\r")
            if not line:                                   # blank line = dispatch
                if data:
                    try:
                        ev = to_event(json.loads("\n".join(data)))
                        if ev:
                            batch.append(validate(ev))
                    except (ValueError, ValidationError):
                        pass
                    if ev_id is not None:
                        last_id = ev_id
                data, ev_id = [], None
            elif not line.startswith(":"):
                field, _, value = line.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if field == "data":
                    data.append(value)
                elif field == "id":
                    ev_id = value
            now = time.monotonic()
            if len(batch) >= 200 or now - last_flush >= 1.0:
                flush()
            if now >= deadline:
                break
    flush()
    return {"status": "ok", "ingested": ingested, "seconds": seconds}
