-- KyberShield Agent Risk Monitor - initial schema.
--
-- Applied by Postgres' docker-entrypoint-initdb.d on a fresh volume. There is
-- no incremental migration tool in this prototype; `make db-reset` recreates
-- the volume and re-runs this file.

BEGIN;

-- Ordered enum so MAX(severity) and severity >= 'high' work directly in SQL.
-- Declaration order defines the ordering.
CREATE TYPE severity AS ENUM ('low', 'medium', 'high', 'critical');

-- ---------------------------------------------------------------------------
-- agents
-- ---------------------------------------------------------------------------
-- Upserted on every ingest so the insights service can enumerate agents
-- without scanning the events table.
CREATE TABLE agents (
    agent_id      TEXT        PRIMARY KEY,
    label         TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- events
-- ---------------------------------------------------------------------------
-- event_id is the primary key, which is the entire idempotency mechanism:
-- ingestion issues INSERT ... ON CONFLICT (event_id) DO NOTHING and reports
-- a zero row count as a duplicate.
--
-- ingest_seq is monotonic in *arrival* order, unlike occurred_at which the
-- agent controls and which may arrive out of order. The analyser polls by
-- ingest_seq so a late event carrying an old timestamp still gets a fresh
-- high sequence number and is picked up on the next pass.
CREATE TABLE events (
    event_id       TEXT        PRIMARY KEY,
    ingest_seq     BIGSERIAL   NOT NULL UNIQUE,
    agent_id       TEXT        NOT NULL REFERENCES agents (agent_id),
    occurred_at    TIMESTAMPTZ NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    type           TEXT        NOT NULL,
    -- Validated and normalised representation, safe for rules to read.
    payload        JSONB       NOT NULL,
    -- Exact envelope as submitted, never rewritten. Kept for forensics and so
    -- historical events can be re-parsed after a schema change.
    raw            JSONB       NOT NULL,
    tags           TEXT[]      NOT NULL DEFAULT '{}',
    -- Which API key submitted this event, for audit.
    client_id      TEXT        NOT NULL,
    schema_version SMALLINT    NOT NULL DEFAULT 1
);

CREATE INDEX events_agent_occurred_idx ON events (agent_id, occurred_at DESC);
CREATE INDEX events_type_idx           ON events (type);
CREATE INDEX events_occurred_idx       ON events (occurred_at DESC);
-- Supports the rapid_secret_reads rule's lookback over one agent's reads.
CREATE INDEX events_agent_type_occurred_idx ON events (agent_id, type, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- alerts
-- ---------------------------------------------------------------------------
-- UNIQUE (event_id, rule) is the alert dedupe mechanism: re-analysing an event
-- is a no-op because the insert conflicts and is skipped. This is what makes
-- backfill and cursor rewinds safe to run repeatedly.
CREATE TABLE alerts (
    alert_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id   TEXT        NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    agent_id   TEXT        NOT NULL REFERENCES agents (agent_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rule       TEXT        NOT NULL,
    severity   severity    NOT NULL,
    summary    TEXT        NOT NULL,
    details    JSONB,
    CONSTRAINT alerts_event_rule_uniq UNIQUE (event_id, rule)
);

CREATE INDEX alerts_created_idx       ON alerts (created_at DESC);
CREATE INDEX alerts_agent_created_idx ON alerts (agent_id, created_at DESC);
CREATE INDEX alerts_rule_idx          ON alerts (rule);
CREATE INDEX alerts_severity_idx      ON alerts (severity);

-- ---------------------------------------------------------------------------
-- analysis_cursor
-- ---------------------------------------------------------------------------
-- Single-row watermark table holding the highest ingest_seq the analyser has
-- processed. The CHECK constraint enforces that exactly one row can exist.
-- Advanced in the same transaction as the alert inserts, so a crash mid-batch
-- rolls back both and the batch is simply retried.
CREATE TABLE analysis_cursor (
    id              SMALLINT    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_ingest_seq BIGINT      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO analysis_cursor (id, last_ingest_seq) VALUES (1, 0);

COMMIT;
