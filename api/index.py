"""Vercel entrypoint: the same Flask app, running as a Python serverless function.

On Vercel (VERCEL env set) the app runs in Postgres-only + polling mode: no WebSockets, no
Redis required, and Wikipedia is pulled on demand by /api/ingest/wikipedia. See README.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

try:
    from app import create_app

    app = create_app()
except Exception as exc:  # surface start-up problems (e.g. no database configured) as JSON
    from flask import Flask, jsonify

    _err = f"{type(exc).__name__}: {exc}".split("\n")[0][:500]
    _where = traceback.format_exc().strip().splitlines()[-3:]
    _hint = ("Add a Postgres database: Vercel project -> Storage -> Create Database -> Neon, "
             "connect it to this project, then redeploy.")
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>", methods=["GET", "POST"])
    def startup_error(path):
        return jsonify(status="startup-error", error=_err, where=_where, hint=_hint), 503
