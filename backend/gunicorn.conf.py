import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
worker_class = "gevent"                 # one greenlet per WebSocket -> thousands per worker
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "2000"))
timeout = 60
graceful_timeout = 20
keepalive = 5
accesslog = "-" if os.getenv("ACCESS_LOG") else None
