from prometheus_client import Counter, Gauge, Histogram

EVENTS_INGESTED = Counter("events_ingested_total", "Events accepted by the ingest API")
INGEST_SECONDS = Histogram("ingest_batch_seconds", "Ingest batch latency (DB + Redis)")
WS_CLIENTS = Gauge("ws_clients", "Open WebSocket connections on this worker")
WS_FRAMES = Counter("ws_frames_sent_total", "WebSocket frames sent")
