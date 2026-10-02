"""Vercel entrypoint: the same Flask app, running as a Python serverless function.

On Vercel (VERCEL env set) the app runs in Postgres-only + polling mode: no WebSockets, no
Redis required, and Wikipedia is pulled on demand by /api/ingest/wikipedia. See README.

Note: Vercel detects the WSGI app by statically looking for a top-level `app = ...`
assignment, so it must stay at module level (not inside try/except).
"""
import sys
import traceback
from pathlib import Path

from flask import Flask, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def _build() -> Flask:
    try:
        from app import create_app

        return create_app()
    except Exception as exc:  # surface start-up problems (e.g. no database) as JSON, not a crash
        err = f"{type(exc).__name__}: {exc}".split("\n")[0][:500]
        where = traceback.format_exc().strip().splitlines()[-3:]
        hint = ("Add a Postgres database: Vercel project -> Storage -> Create Database -> Neon, "
                "connect it to this project, then redeploy.")
        fallback = Flask(__name__)

        @fallback.route("/", defaults={"path": ""})
        @fallback.route("/<path:path>", methods=["GET", "POST"])
        def startup_error(path):
            return jsonify(status="startup-error", error=err, where=where, hint=hint), 503

        return fallback


app = _build()
