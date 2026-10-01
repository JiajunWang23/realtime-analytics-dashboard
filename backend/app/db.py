from contextlib import contextmanager
from pathlib import Path

from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None


def init_pool(cfg):
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(cfg.DB_POOL_MIN, cfg.DB_POOL_MAX, cfg.DATABASE_URL)
    return _pool


@contextmanager
def get_conn():
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def apply_schema():
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with get_conn() as conn, conn.cursor() as cur:
        # Serialize schema creation across pods starting at the same time.
        cur.execute("SELECT pg_advisory_xact_lock(424242)")
        cur.execute(sql)
