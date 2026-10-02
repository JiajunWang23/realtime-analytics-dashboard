import json
import logging
import os
import queue
import time

from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import stats
from .config import Config
from .db import apply_schema, get_conn, init_pool
from .ingest import SOURCE_RE, ValidationError, ingest, validate
from .metrics import WS_FRAMES
from .redis_client import init_redis, r

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

BOT_UA = ("bot", "crawl", "spider", "slurp", "headless", "lighthouse", "preview", "curl", "python-")


def create_app(cfg=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(cfg)

    init_pool(cfg)
    init_redis(cfg)
    apply_schema()
    # WebSocket fan-out needs long-lived processes + Redis pub/sub. Where that's not available
    # (serverless), clients poll /api/live instead and the same data flows through Postgres.
    ws_enabled = cfg.REALTIME == "ws" and r() is not None
    if ws_enabled:
        from flask_sock import Sock
        from .hub import Hub
        sock = Sock(app)
        app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": cfg.WS_PING_SECONDS}
        hub = Hub(cfg)
        hub.start()
    local_rate: dict[str, int] = {}

    @app.after_request
    def cors(resp):
        origin = request.headers.get("Origin")
        if request.path == "/api/collect":
            if origin in cfg.COLLECT_ORIGINS:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
        else:
            resp.headers["Access-Control-Allow-Origin"] = cfg.CORS_ORIGIN
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    def _accept(raw, source=None):
        if not isinstance(raw, list) or not raw:
            return jsonify(error="body must be an event or {events: [...]}"), 400
        if len(raw) > cfg.MAX_BATCH:
            return jsonify(error=f"max {cfg.MAX_BATCH} events per request"), 413
        try:
            events = [validate(e, source) for e in raw]
        except (ValidationError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(accepted=ingest(events, cfg.EVENTS_CHANNEL, cfg.DIM_KEYS)), 202

    # ---------------- ingest: trusted producers (connectors, simulator) ----------------
    @app.post("/api/events")
    def post_events():
        body = request.get_json(silent=True)
        raw = body.get("events") if isinstance(body, dict) and "events" in body else [body]
        return _accept(raw)

    # ---------------- ingest: browser beacons from the personal website ----------------
    # navigator.sendBeacon posts text/plain (no CORS preflight), so parse the raw body.
    # Source is forced to "site"; bots are dropped; per-IP rate limit; IP is never stored.
    @app.route("/api/collect", methods=["POST", "OPTIONS"])
    def collect():
        if request.method == "OPTIONS":
            return "", 204
        origin = request.headers.get("Origin")
        if cfg.COLLECT_ORIGINS and origin not in cfg.COLLECT_ORIGINS:
            return jsonify(error="origin not allowed"), 403
        ua = (request.headers.get("User-Agent") or "").lower()
        if not ua or any(b in ua for b in BOT_UA):
            return "", 204
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0]
        key = f"rl:collect:{ip}:{int(time.time() // 60)}"
        if r() is not None:
            pipe = r().pipeline()
            pipe.incr(key)
            pipe.expire(key, 120)
            hits = pipe.execute()[0]
        else:                                  # per-instance limit when there's no Redis
            if len(local_rate) > 10_000:
                local_rate.clear()
            hits = local_rate[key] = local_rate.get(key, 0) + 1
        if hits > cfg.COLLECT_RATE_PER_MIN:
            return jsonify(error="rate limited"), 429
        try:
            body = json.loads(request.get_data(as_text=True) or "{}")
        except ValueError:
            return jsonify(error="invalid JSON"), 400
        raw = body.get("events") if isinstance(body, dict) else None
        if isinstance(raw, list) and len(raw) > 20:
            return jsonify(error="max 20 events per beacon"), 413
        return _accept(raw, source="site")

    # ---------------- read API ----------------
    def _minutes():
        return max(1, min(int(request.args.get("minutes", 60)), 7 * 24 * 60))

    def _source():
        s = request.args.get("source", "site")
        if not SOURCE_RE.match(s):
            raise ValidationError("bad source")
        return s

    @app.errorhandler(ValidationError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    @app.get("/api/sources")
    def sources():
        return jsonify(cfg.SOURCES)

    @app.get("/api/stats/summary")
    def summary():
        return jsonify(stats.all_summaries(cfg.SOURCES))

    @app.get("/api/stats/timeseries")
    def ts():
        return jsonify(stats.timeseries(_source(), _minutes()))

    @app.get("/api/stats/breakdown")
    def bd():
        return jsonify(stats.breakdown(_source(), _minutes()))

    @app.get("/api/stats/dims")
    def dims():
        key = request.args.get("key", "")
        if key not in cfg.DIM_KEYS:
            return jsonify(error=f"key must be one of {cfg.DIM_KEYS}"), 400
        limit = max(1, min(int(request.args.get("limit", 10)), 50))
        return jsonify(stats.dims(_source(), key, _minutes(), limit))

    @app.get("/api/events/recent")
    def recent():
        return jsonify(stats.recent(_source(), max(1, min(int(request.args.get("limit", 50)), 200))))

    @app.get("/api/config")
    def client_config():
        return jsonify(realtime="ws" if ws_enabled else "poll", wiki_pull=cfg.WIKI_PULL_ENABLED)

    # ---------------- polling transport (used when WebSockets aren't available) ----------------
    @app.get("/api/live")
    def live():
        after = request.args.get("after")
        limit = max(1, min(int(request.args.get("limit", 500)), 1000))
        return jsonify(stats.live(_source(), int(after) if after not in (None, "") else None, limit))

    # ---------------- on-demand Wikipedia pull (serverless replacement for the connector) -------
    @app.route("/api/ingest/wikipedia", methods=["GET", "POST"])
    def wiki_pull():
        if not cfg.WIKI_PULL_ENABLED:
            return jsonify(status="disabled", detail="the always-on connector is used instead"), 404
        from .wikipull import pull
        seconds = max(1, min(int(request.args.get("seconds", cfg.WIKI_PULL_SECONDS)), cfg.WIKI_PULL_MAX_SECONDS))
        try:
            return jsonify(pull(cfg, seconds))
        except Exception as exc:              # upstream stream hiccup: report, don't 500-loop
            logging.getLogger(__name__).warning("wikipedia pull failed: %s", exc)
            return jsonify(status="error", error=str(exc)), 502

    # ---------------- WebSocket ----------------
    def ws(conn):
        # /ws?source=wikipedia -> only that stream's events (stats frames go to everyone)
        src = request.args.get("source", "*")
        client = hub.register(src if src == "*" or SOURCE_RE.match(src) else "*")
        try:
            conn.send(json.dumps({"kind": "hello", **stats.all_summaries(cfg.SOURCES)}))
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

    if ws_enabled:
        sock.route("/ws")(ws)

    # ---------------- tracker script for the personal website ----------------
    tracker_js = (Path(__file__).resolve().parents[2] / "tracker" / "rta.js")
    if not tracker_js.exists():                      # container layout: /app/tracker/rta.js
        tracker_js = Path(__file__).resolve().parents[1] / "tracker" / "rta.js"

    @app.get("/rta.js")
    def rta_js():
        return send_file(tracker_js, mimetype="application/javascript", max_age=3600)

    # ---------------- optional: serve the built dashboard (single-origin local runs) ----------
    dist = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    if (dist / "index.html").exists():
        @app.get("/")
        def spa_index():
            return send_from_directory(dist, "index.html")

        @app.get("/assets/<path:name>")
        def spa_assets(name):
            return send_from_directory(dist / "assets", name, max_age=86400)

        @app.get("/favicon.svg")
        def spa_favicon():
            return send_from_directory(dist, "favicon.svg", max_age=86400)

    # ---------------- ops ----------------
    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz():
        try:
            if r() is not None:
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
