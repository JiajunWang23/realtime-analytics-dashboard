"""Event ingestion: validate -> Postgres (raw + rollup) -> Redis counters -> Redis PUBLISH."""
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

from psycopg2.extras import Json, execute_values

from .db import get_conn
from .metrics import EVENTS_INGESTED, INGEST_SECONDS
from .redis_client import r

TTL = 3 * 3600           # per-minute keys
DAY_TTL = 3 * 86400      # per-day keys
SOURCE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
MAX_DIM_LEN = 120


class ValidationError(ValueError):
    pass


def _parse_ts(raw):
    if raw is None:
        return datetime.now(timezone.utc)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw / 1000 if raw > 1e11 else raw, tz=timezone.utc)
    if isinstance(raw, str):
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValidationError("ts must be ISO-8601 string or epoch number")


def validate(raw: dict, source: str | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("event must be an object")
    etype = raw.get("type")
    uid = raw.get("user_id")
    src = source or raw.get("source", "demo")
    if not isinstance(src, str) or not SOURCE_RE.match(src):
        raise ValidationError("source: [a-z0-9_-]{1,32}")
    if not isinstance(etype, str) or not 0 < len(etype) <= 64:
        raise ValidationError("type: non-empty string <= 64 chars required")
    if not isinstance(uid, str) or not 0 < len(uid) <= 128:
        raise ValidationError("user_id: non-empty string <= 128 chars required")
    value = raw.get("value", 0)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError("value must be a number")
    props = raw.get("props", {})
    if not isinstance(props, dict) or len(json.dumps(props)) > 4096:
        raise ValidationError("props must be an object (<= 4 KB)")
    ts = _parse_ts(raw.get("ts"))
    now = datetime.now(timezone.utc)
    if abs((ts - now).total_seconds()) > 86400:   # clock-skewed clients: trust the server
        ts = now
    return {"source": src, "type": etype, "user_id": uid, "value": float(value),
            "props": props, "occurred_at": ts}


def ingest(events: list[dict], channel: str, dim_keys: list[str]) -> int:
    t0 = time.perf_counter()
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    # 1) Postgres: raw insert + per-minute rollup upsert in ONE transaction.
    rollup = defaultdict(lambda: [0, 0.0])
    for e in events:
        agg = rollup[(e["source"], e["occurred_at"].replace(second=0, microsecond=0), e["type"])]
        agg[0] += 1
        agg[1] += e["value"]

    with get_conn() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO events (source, event_type, user_id, value, props, occurred_at, ingested_at)
               VALUES %s""",
            [(e["source"], e["type"], e["user_id"], e["value"], Json(e["props"]), e["occurred_at"], now)
             for e in events],
            page_size=1000,
        )
        execute_values(
            cur,
            """INSERT INTO event_rollup_minute (source, bucket, event_type, cnt, value_sum) VALUES %s
               ON CONFLICT (source, bucket, event_type) DO UPDATE
               SET cnt = event_rollup_minute.cnt + EXCLUDED.cnt,
                   value_sum = event_rollup_minute.value_sum + EXCLUDED.value_sum""",
            # sorted -> consistent lock order across concurrent writers (no deadlocks)
            sorted((s, b, t, c, v) for (s, b, t), (c, v) in rollup.items()),
        )

    if r() is None:                       # Postgres-only mode (e.g. Vercel)
        EVENTS_INGESTED.inc(len(events))
        INGEST_SECONDS.observe(time.perf_counter() - t0)
        return len(events)

    # 2) Redis, one round trip: live counters, HyperLogLog uniques, dimension top-N,
    #    recent feed, and PUBLISH for the WebSocket fan-out.
    payload = [{
        "source": e["source"], "type": e["type"], "user_id": e["user_id"], "value": e["value"],
        "props": e["props"], "occurred_at": e["occurred_at"].isoformat(), "ingested_at": now_ms,
    } for e in events]
    day = now.strftime("%Y%m%d")

    counts = defaultdict(int)          # (src, minute) -> n
    users = defaultdict(set)           # (src, minute) -> {user}
    day_users = defaultdict(set)       # src -> {user}
    per_src = defaultdict(int)         # src -> n
    types = defaultdict(int)           # (src, type) -> n
    dims = defaultdict(int)            # (src, key, minute, value) -> n
    feed = defaultdict(list)           # src -> [json]
    for e, p in zip(events, payload):
        s = e["source"]
        m = int(e["occurred_at"].timestamp() // 60)
        counts[(s, m)] += 1
        users[(s, m)].add(e["user_id"])
        day_users[s].add(e["user_id"])
        per_src[s] += 1
        types[(s, e["type"])] += 1
        for k in dim_keys:
            v = e["props"].get(k)
            if v is not None and v != "":
                dims[(s, k, m, str(v)[:MAX_DIM_LEN])] += 1
        feed[s].append(json.dumps(p))

    pipe = r().pipeline(transaction=False)
    for s, n in per_src.items():
        pipe.incrby(f"stats:total:{s}:{day}", n)
        pipe.expire(f"stats:total:{s}:{day}", DAY_TTL)
        pipe.pfadd(f"hll:users:{s}:day:{day}", *day_users[s])
        pipe.expire(f"hll:users:{s}:day:{day}", DAY_TTL)
        pipe.lpush(f"feed:{s}", *feed[s][-50:])
        pipe.ltrim(f"feed:{s}", 0, 199)
    for (s, m), n in counts.items():
        pipe.incrby(f"stats:min:{s}:{m}", n)
        pipe.expire(f"stats:min:{s}:{m}", TTL)
        pipe.pfadd(f"hll:users:{s}:{m}", *users[(s, m)])
        pipe.expire(f"hll:users:{s}:{m}", TTL)
    for (s, t), n in types.items():
        pipe.hincrby(f"stats:types:{s}:{day}", t, n)
        pipe.expire(f"stats:types:{s}:{day}", DAY_TTL)
    for (s, k, m, v), n in dims.items():
        pipe.hincrby(f"dim:{s}:{k}:{m}", v, n)
        pipe.expire(f"dim:{s}:{k}:{m}", TTL)
    pipe.publish(channel, json.dumps({"kind": "events", "events": payload}))
    pipe.execute()

    EVENTS_INGESTED.inc(len(events))
    INGEST_SECONDS.observe(time.perf_counter() - t0)
    return len(events)
