"""Read side. Live KPIs come from Redis (O(1)); history comes from the Postgres rollup."""
import json
import time
from collections import Counter
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

from .db import get_conn
from .redis_client import r


def live_summary(source: str) -> dict:
    now_min = int(time.time() // 60)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    pipe = r().pipeline(transaction=False)
    pipe.get(f"stats:min:{source}:{now_min - 1}")              # last full minute
    pipe.get(f"stats:min:{source}:{now_min}")                  # current partial minute
    pipe.get(f"stats:total:{source}:{day}")
    pipe.pfcount(*[f"hll:users:{source}:{m}" for m in range(now_min - 4, now_min + 1)])
    pipe.pfcount(f"hll:users:{source}:day:{day}")
    last_min, cur_min, total, active, uniq_today = pipe.execute()
    return {
        "events_last_minute": int(last_min or 0),
        "events_this_minute": int(cur_min or 0),
        "events_today": int(total or 0),
        "active_users_5m": int(active or 0),
        "unique_users_today": int(uniq_today or 0),
    }


def ws_clients() -> int:
    keys = list(r().scan_iter("ws:clients:*", count=100))   # one heartbeat key per worker
    return sum(int(v or 0) for v in r().mget(keys)) if keys else 0


def all_summaries(sources: list[str]) -> dict:
    return {"sources": {s: live_summary(s) for s in sources},
            "ws_clients": ws_clients(), "server_time": int(time.time() * 1000)}


def dims(source: str, key: str, minutes: int = 60, limit: int = 10) -> list[dict]:
    """Top-N values of props[key] over the last `minutes`, merged from per-minute Redis hashes."""
    now_min = int(time.time() // 60)
    pipe = r().pipeline(transaction=False)
    for m in range(now_min - minutes + 1, now_min + 1):
        pipe.hgetall(f"dim:{source}:{key}:{m}")
    total = Counter()
    for h in pipe.execute():
        for v, n in h.items():
            total[v] += int(n)
    return [{"value": v, "count": n} for v, n in total.most_common(limit)]


def timeseries(source: str, minutes: int = 60) -> list[dict]:
    sql = """
        SELECT bucket, event_type, cnt, value_sum
        FROM event_rollup_minute
        WHERE source = %s AND bucket >= date_trunc('minute', now()) - make_interval(mins => %s)
        ORDER BY bucket
    """
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (source, minutes))
        rows = cur.fetchall()
    return [{"bucket": row["bucket"].isoformat(), "type": row["event_type"],
             "count": row["cnt"], "value_sum": row["value_sum"]} for row in rows]


def breakdown(source: str, minutes: int = 60) -> list[dict]:
    sql = """
        SELECT event_type, SUM(cnt)::bigint AS count, SUM(value_sum) AS value_sum
        FROM event_rollup_minute
        WHERE source = %s AND bucket >= date_trunc('minute', now()) - make_interval(mins => %s)
        GROUP BY event_type ORDER BY count DESC
    """
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (source, minutes))
        return [dict(row) for row in cur.fetchall()]


def recent(source: str, limit: int = 50) -> list[dict]:
    return [json.loads(x) for x in r().lrange(f"feed:{source}", 0, limit - 1)]
