"""Event ingestion: validate -> Postgres (raw + rollup) -> Redis counters -> Redis PUBLISH."""
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

from psycopg2.extras import Json, execute_values

from .db import get_conn
from .metrics import EVENTS_INGESTED, INGEST_SECONDS
from .redis_client import r

ROLLUP_TTL = 3 * 3600


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


def validate(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("event must be an object")
    etype = raw.get("type")
    uid = raw.get("user_id")
    if not isinstance(etype, str) or not 0 < len(etype) <= 64:
        raise ValidationError("type: non-empty string <= 64 chars required")
    if not isinstance(uid, str) or not 0 < len(uid) <= 128:
        raise ValidationError("user_id: non-empty string <= 128 chars required")
    value = raw.get("value", 0)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError("value must be a number")
    props = raw.get("props", {})
    if not isinstance(props, dict):
        raise ValidationError("props must be an object")
    return {"type": etype, "user_id": uid, "value": float(value), "props": props,
            "occurred_at": _parse_ts(raw.get("ts"))}


def ingest(events: list[dict], channel: str) -> int:
    t0 = time.perf_counter()
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    # 1) Postgres: raw insert + per-minute rollup upsert in ONE transaction.
    rollup = defaultdict(lambda: [0, 0.0])
    for e in events:
        bucket = e["occurred_at"].replace(second=0, microsecond=0)
        agg = rollup[(bucket, e["type"])]
        agg[0] += 1
        agg[1] += e["value"]

    with get_conn() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO events (event_type, user_id, value, props, occurred_at, ingested_at) VALUES %s",
            [(e["type"], e["user_id"], e["value"], Json(e["props"]), e["occurred_at"], now) for e in events],
            page_size=1000,
        )
        execute_values(
            cur,
            """INSERT INTO event_rollup_minute (bucket, event_type, cnt, value_sum) VALUES %s
               ON CONFLICT (bucket, event_type) DO UPDATE
               SET cnt = event_rollup_minute.cnt + EXCLUDED.cnt,
                   value_sum = event_rollup_minute.value_sum + EXCLUDED.value_sum""",
            # sorted -> consistent lock order across concurrent writers (no deadlocks)
            sorted((b, t, c, s) for (b, t), (c, s) in rollup.items()),
        )

    # 2) Redis: live counters + HyperLogLog active users + recent feed + PUBLISH, one round trip.
    payload = [{
        "type": e["type"], "user_id": e["user_id"], "value": e["value"], "props": e["props"],
        "occurred_at": e["occurred_at"].isoformat(), "ingested_at": now_ms,
    } for e in events]
    day = now.strftime("%Y%m%d")
    pipe = r().pipeline(transaction=False)
    pipe.incrby(f"stats:total:{day}", len(events))
    pipe.expire(f"stats:total:{day}", 3 * 86400)
    per_min_users = defaultdict(set)
    per_min_counts = defaultdict(int)
    per_type_today = defaultdict(int)
    for e in events:
        m = int(e["occurred_at"].timestamp() // 60)
        per_min_users[m].add(e["user_id"])
        per_min_counts[m] += 1
        per_type_today[e["type"]] += 1
    for m, n in per_min_counts.items():
        pipe.incrby(f"stats:min:{m}", n)
        pipe.expire(f"stats:min:{m}", ROLLUP_TTL)
    for m, users in per_min_users.items():
        pipe.pfadd(f"hll:users:{m}", *users)
        pipe.expire(f"hll:users:{m}", ROLLUP_TTL)
    for t, n in per_type_today.items():
        pipe.hincrby(f"stats:types:{day}", t, n)
    pipe.expire(f"stats:types:{day}", 3 * 86400)
    pipe.lpush("feed:recent", *[json.dumps(p) for p in payload[-50:]])
    pipe.ltrim("feed:recent", 0, 199)
    pipe.publish(channel, json.dumps({"kind": "events", "events": payload}))
    pipe.execute()

    EVENTS_INGESTED.inc(len(events))
    INGEST_SECONDS.observe(time.perf_counter() - t0)
    return len(events)
