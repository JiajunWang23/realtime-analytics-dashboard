import redis

_r: redis.Redis | None = None


def init_redis(cfg):
    """Returns None when REDIS_URL is empty: the app then runs in Postgres-only mode."""
    global _r
    if _r is None and cfg.REDIS_URL:
        _r = redis.Redis.from_url(cfg.REDIS_URL, decode_responses=True,
                                  health_check_interval=30, socket_keepalive=True)
    return _r


def r() -> redis.Redis | None:
    return _r
