"""Read side. Live KPIs come from Redis (O(1)); history comes from the Postgres rollup."""
import json
import time
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

from .db import get_conn
from .redis_client import r


def live_summary() -> dict:
    now_min = int(time.time() // 60)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    pipe = r().pipeline(transaction=False)
    pipe.get(f"stats:min:{now_min - 1}")              # last full minute
    pipe.get(f"stats:min:{now_min}")                  # current partial minute
    pipe.get(f"stats:total:{day}")
    pipe.pfcount(*[f"hll:users:{m}" for m in range(now_min - 4, now_min + 1)])
    last_min, cur_min, total, active = pipe.execute()
    keys = list(r().scan_iter("ws:clients:*", count=100))   # one heartbeat key per worker
    ws = sum(int(v or 0) for v in r().mget(keys)) if keys else 0
    return {
        "events_last_minute": int(last_min or 0),
        "events_this_minute": int(cur_min or 0),
        "events_today": int(total or 0),
        "active_users_5m": int(active or 0),
        "ws_clients": ws,
        "server_time": int(time.time() * 1000),
    }


def timeseries(minutes: int = 60) -> list[dict]:
    sql = """
        SELECT bucket, event_type, cnt, value_sum
        FROM event_rollup_minute
        WHERE bucket >= date_trunc('minute', now()) - make_interval(mins => %s)
        ORDER BY bucket
    """
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (minutes,))
        rows = cur.fetchall()
    return [{"bucket": row["bucket"].isoformat(), "type": row["event_type"],
             "count": row["cnt"], "value_sum": row["value_sum"]} for row in rows]


def breakdown(minutes: int = 60) -> list[dict]:
    sql = """
        SELECT event_type, SUM(cnt)::bigint AS count, SUM(value_sum) AS value_sum
        FROM event_rollup_minute
        WHERE bucket >= date_trunc('minute', now()) - make_interval(mins => %s)
        GROUP BY event_type ORDER BY count DESC
    """
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (minutes,))
        return [dict(row) for row in cur.fetchall()]


def recent(limit: int = 50) -> list[dict]:
    return [json.loads(x) for x in r().lrange("feed:recent", 0, limit - 1)]
