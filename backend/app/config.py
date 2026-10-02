import os

# On Vercel there are no long-lived processes or WebSockets: realtime falls back to HTTP
# polling, Redis is optional (Postgres alone serves every endpoint), and Wikipedia is pulled
# on demand by /api/ingest/wikipedia instead of the always-on connector.
ON_VERCEL = bool(os.getenv("VERCEL"))


class Config:
    DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
                    or "postgresql://postgres:postgres@localhost:5432/analytics")
    # Empty string = run without Redis (Postgres-only mode).
    REDIS_URL = os.getenv("REDIS_URL", os.getenv("KV_URL", "" if ON_VERCEL else "redis://localhost:6379/0"))
    REALTIME = os.getenv("REALTIME", "poll" if ON_VERCEL else "ws")     # "ws" | "poll"
    DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "0" if ON_VERCEL else "2"))
    DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "5" if ON_VERCEL else "20"))
    # Redis pub/sub channel every pod subscribes to.
    EVENTS_CHANNEL = os.getenv("EVENTS_CHANNEL", "analytics:events")
    # Fan-out batching window. Small enough to keep end-to-end latency < 100 ms,
    # large enough to coalesce bursts into one WebSocket frame per client.
    BROADCAST_WINDOW_MS = int(os.getenv("BROADCAST_WINDOW_MS", "10"))
    MAX_BATCH = int(os.getenv("MAX_BATCH", "1000"))
    WS_PING_SECONDS = int(os.getenv("WS_PING_SECONDS", "20"))
    CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")
    # Streams shown on the dashboard; per-source KPIs are broadcast for each.
    SOURCES = os.getenv("SOURCES", "site,wikipedia,demo").split(",")
    # props keys that get live top-N counters in Redis (cheap breakdowns, no SQL).
    DIM_KEYS = os.getenv("DIM_KEYS", "ref_source,path,target,wiki,bot").split(",")
    # /api/collect: browser beacons from the personal website.
    COLLECT_ORIGINS = [o for o in os.getenv(
        "COLLECT_ORIGINS",
        "https://uiucwangjiajun.com,https://www.uiucwangjiajun.com,http://localhost:5173,http://localhost:8080",
    ).split(",") if o]
    COLLECT_RATE_PER_MIN = int(os.getenv("COLLECT_RATE_PER_MIN", "120"))  # per client IP

    # On-demand Wikipedia pull (serverless replacement for connectors/wikipedia.py).
    WIKI_PULL_ENABLED = os.getenv("WIKI_PULL_ENABLED", "1" if ON_VERCEL else "0") == "1"
    WIKI_STREAM_URL = os.getenv("WIKI_STREAM_URL", "https://stream.wikimedia.org/v2/stream/recentchange")
    WIKI_PULL_SECONDS = int(os.getenv("WIKI_PULL_SECONDS", "25"))
    WIKI_PULL_MAX_SECONDS = int(os.getenv("WIKI_PULL_MAX_SECONDS", "45"))
    # Keep raw Wikipedia rows this long (rollups are kept forever). 0 = keep everything.
    WIKI_RETENTION_HOURS = int(os.getenv("WIKI_RETENTION_HOURS", "48" if ON_VERCEL else "0"))
