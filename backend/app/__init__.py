import json
import logging
import queue

from flask import Flask, jsonify, request
from flask_sock import Sock
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import stats
from .config import Config
from .db import apply_schema, get_conn, init_pool
from .hub import Hub
from .ingest import ValidationError, ingest, validate
from .metrics import WS_FRAMES
from .redis_client import init_redis, r

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(cfg=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(cfg)
    sock = Sock(app)
    app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": cfg.WS_PING_SECONDS}

    init_pool(cfg)
    init_redis(cfg)
    apply_schema()
    hub = Hub(cfg)
    hub.start()

    @app.after_request
    def cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = cfg.CORS_ORIGIN
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    # ---------------- ingest ----------------
    @app.post("/api/events")
    def post_events():
        body = request.get_json(silent=True)
        raw = body.get("events") if isinstance(body, dict) and "events" in body else [body]
        if not isinstance(raw, list) or not raw:
            return jsonify(error="body must be an event or {events: [...]}"), 400
        if len(raw) > cfg.MAX_BATCH:
            return jsonify(error=f"max {cfg.MAX_BATCH} events per request"), 413
        try:
            events = [validate(e) for e in raw]
        except (ValidationError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        n = ingest(events, cfg.EVENTS_CHANNEL)
        return jsonify(accepted=n), 202

    # ---------------- read API ----------------
    def _minutes():
        return max(1, min(int(request.args.get("minutes", 60)), 7 * 24 * 60))

    @app.get("/api/stats/summary")
    def summary():
        return jsonify(stats.live_summary())

    @app.get("/api/stats/timeseries")
    def ts():
        return jsonify(stats.timeseries(_minutes()))

    @app.get("/api/stats/breakdown")
    def bd():
        return jsonify(stats.breakdown(_minutes()))

    @app.get("/api/events/recent")
    def recent():
        return jsonify(stats.recent(max(1, min(int(request.args.get("limit", 50)), 200))))

    # ---------------- WebSocket ----------------
    @sock.route("/ws")
    def ws(conn):
        client = hub.register()
        try:
            conn.send(json.dumps({"kind": "hello", **stats.live_summary()}))
            while True:
                try:
                    frame = client.q.get(timeout=cfg.WS_PING_SECONDS)
                except queue.Empty:
                    frame = json.dumps({"kind": "ping"})
                conn.send(frame)            # raises once the peer is gone
                WS_FRAMES.inc()
        except Exception:
            pass
        finally:
            hub.unregister(client)

    # ---------------- ops ----------------
    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz():
        try:
            r().ping()
            with get_conn() as c, c.cursor() as cur:
                cur.execute("SELECT 1")
            return jsonify(status="ready")
        except Exception as exc:
            return jsonify(status="not-ready", error=str(exc)), 503

    @app.get("/metrics")
    def metrics():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    return app
