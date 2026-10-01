import os


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/analytics")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
    DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "20"))
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
