"""Vercel entrypoint: the same Flask app, running as a Python serverless function.

On Vercel (VERCEL env set) the app runs in Postgres-only + polling mode: no WebSockets, no
Redis required, and Wikipedia is pulled on demand by /api/ingest/wikipedia. See README.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import create_app  # noqa: E402

app = create_app()
