import redis

_r: redis.Redis | None = None


def init_redis(cfg):
    global _r
    if _r is None:
        _r = redis.Redis.from_url(cfg.REDIS_URL, decode_responses=True,
                                  health_check_interval=30, socket_keepalive=True)
    return _r


def r() -> redis.Redis:
    return _r
