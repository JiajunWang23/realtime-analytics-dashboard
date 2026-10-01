-- Raw event log (append-only). 5M+ rows target.
CREATE TABLE IF NOT EXISTS events (
    id           BIGSERIAL PRIMARY KEY,
    event_type   TEXT             NOT NULL,
    user_id      TEXT             NOT NULL,
    value        DOUBLE PRECISION NOT NULL DEFAULT 0,
    props        JSONB            NOT NULL DEFAULT '{}'::jsonb,
    occurred_at  TIMESTAMPTZ      NOT NULL,
    ingested_at  TIMESTAMPTZ      NOT NULL DEFAULT now()
);

-- BRIN: tiny index for time-range scans on an append-only, time-ordered table.
CREATE INDEX IF NOT EXISTS events_occurred_brin ON events USING BRIN (occurred_at);
-- Composite B-tree for "per-type over a time window" drill-downs.
CREATE INDEX IF NOT EXISTS events_type_time_idx ON events (event_type, occurred_at DESC);
-- Per-user lookups (user timeline, active-user checks).
CREATE INDEX IF NOT EXISTS events_user_time_idx ON events (user_id, occurred_at DESC);

-- Pre-aggregated per-minute rollup, upserted on every ingest batch.
-- Dashboard queries read this instead of scanning raw events.
CREATE TABLE IF NOT EXISTS event_rollup_minute (
    bucket      TIMESTAMPTZ      NOT NULL,
    event_type  TEXT             NOT NULL,
    cnt         BIGINT           NOT NULL DEFAULT 0,
    value_sum   DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, event_type)
);
CREATE INDEX IF NOT EXISTS rollup_bucket_idx ON event_rollup_minute (bucket DESC);
