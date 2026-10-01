"""Seed 5M+ events and measure dashboard query latency three ways.

  python scripts/bench_query.py --seed 5000000     # seed (once), then benchmark
  python scripts/bench_query.py                    # benchmark only

Strategies compared, for the dashboard queries (per-minute series over 24h, type
breakdown over 24h, one type drill-down over 6h):
  A. raw table, no secondary indexes (sequential scans)
  B. raw table + BRIN(occurred_at) + B-tree(event_type, occurred_at)
  C. pre-aggregated per-minute rollup table (what the API actually serves)
"""
import argparse
import os
import statistics
import time

import psycopg2

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/analytics")

QUERIES_RAW = {
    "series_24h": """SELECT date_trunc('minute', occurred_at) b, event_type, count(*), sum(value)
                     FROM events WHERE occurred_at >= now() - interval '24 hours'
                     GROUP BY 1, 2""",
    "breakdown_24h": """SELECT event_type, count(*), sum(value) FROM events
                        WHERE occurred_at >= now() - interval '24 hours' GROUP BY 1""",
    "drilldown_purchase_6h": """SELECT date_trunc('minute', occurred_at), count(*), sum(value)
                                FROM events WHERE event_type = 'purchase'
                                AND occurred_at >= now() - interval '6 hours' GROUP BY 1""",
}
QUERIES_ROLLUP = {
    "series_24h": """SELECT bucket, event_type, cnt, value_sum FROM event_rollup_minute
                     WHERE bucket >= now() - interval '24 hours'""",
    "breakdown_24h": """SELECT event_type, sum(cnt), sum(value_sum) FROM event_rollup_minute
                        WHERE bucket >= now() - interval '24 hours' GROUP BY 1""",
    "drilldown_purchase_6h": """SELECT bucket, cnt, value_sum FROM event_rollup_minute
                                WHERE event_type = 'purchase'
                                AND bucket >= now() - interval '6 hours'""",
}
INDEXES = {
    "events_occurred_brin": "CREATE INDEX events_occurred_brin ON events USING BRIN (occurred_at)",
    "events_type_time_idx": "CREATE INDEX events_type_time_idx ON events (event_type, occurred_at DESC)",
}

SEED_SQL = """
INSERT INTO events (event_type, user_id, value, props, occurred_at, ingested_at)
SELECT (ARRAY['page_view','page_view','page_view','page_view','page_view','page_view',
              'click','click','click','add_to_cart','purchase','signup','error'])[1 + (random()*12)::int],
       'u' || (random()*50000)::int,
       round((random()*100)::numeric, 2),
       jsonb_build_object('page', (ARRAY['/','/pricing','/docs','/blog','/checkout'])[1 + (random()*4)::int]),
       ts, ts
FROM (SELECT now() - interval '30 days' + (g * (interval '30 days' / %(n)s)) AS ts
      FROM generate_series(1, %(n)s) g) s
"""
BACKFILL_ROLLUP = """
INSERT INTO event_rollup_minute (bucket, event_type, cnt, value_sum)
SELECT date_trunc('minute', occurred_at), event_type, count(*), sum(value)
FROM events GROUP BY 1, 2
ON CONFLICT (bucket, event_type) DO UPDATE SET cnt = EXCLUDED.cnt, value_sum = EXCLUDED.value_sum
"""


def timed(cur, sql, runs):
    cur.execute(sql)  # warm cache
    cur.fetchall()
    out = []
    for _ in range(runs):
        t = time.perf_counter()
        cur.execute(sql)
        cur.fetchall()
        out.append((time.perf_counter() - t) * 1000)
    return statistics.mean(out)


def main(a):
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()
    if a.seed:
        print(f"seeding {a.seed:,} events over 30 days ...")
        t = time.time()
        cur.execute("SET maintenance_work_mem = '512MB'")
        cur.execute(SEED_SQL, {"n": a.seed})
        cur.execute("TRUNCATE event_rollup_minute")
        cur.execute(BACKFILL_ROLLUP)
        cur.execute("VACUUM ANALYZE events")
        cur.execute("VACUUM ANALYZE event_rollup_minute")
        print(f"seeded in {time.time() - t:.0f}s")

    cur.execute("SELECT count(*) FROM events")
    n_events = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM event_rollup_minute")
    n_rollup = cur.fetchone()[0]
    print(f"events={n_events:,} rollup_rows={n_rollup:,}\n")

    # A: drop secondary indexes
    for name in INDEXES:
        cur.execute(f"DROP INDEX IF EXISTS {name}")
    cur.execute("ANALYZE events")
    res_a = {k: timed(cur, q, a.runs) for k, q in QUERIES_RAW.items()}
    # B: indexed raw
    for ddl in INDEXES.values():
        cur.execute(ddl)
    cur.execute("ANALYZE events")
    res_b = {k: timed(cur, q, a.runs) for k, q in QUERIES_RAW.items()}
    # C: rollup
    res_c = {k: timed(cur, q, a.runs) for k, q in QUERIES_ROLLUP.items()}

    print(f"{'query':<24}{'A raw/no-idx':>14}{'B raw+idx':>12}{'C rollup':>12}")
    for k in QUERIES_RAW:
        print(f"{k:<24}{res_a[k]:>12.1f}ms{res_b[k]:>10.1f}ms{res_c[k]:>10.1f}ms")
    avg = lambda d: statistics.mean(d.values())  # noqa: E731
    print(f"{'average':<24}{avg(res_a):>12.1f}ms{avg(res_b):>10.1f}ms{avg(res_c):>10.1f}ms")
    print(f"\nindexes alone (A->B): {100 * (1 - avg(res_b) / avg(res_a)):.1f}% faster")
    print(f"indexed rollup (A->C): {100 * (1 - avg(res_c) / avg(res_a)):.1f}% faster")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--runs", type=int, default=5)
    main(p.parse_args())
