-- ---------------------------------------------------------------------------
-- Push notification of new events
-- ---------------------------------------------------------------------------
-- Replaces the analyser's fixed polling latency with a wakeup at commit time.
-- The notification is a signal only, never data: the analyser still drains via
-- `ingest_seq` past its stored cursor, so a missed or duplicated notification
-- costs latency, never correctness. That matters because NOTIFY is not durable
-- and is dropped entirely if no session is listening.

CREATE OR REPLACE FUNCTION notify_events_ingested() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- `inserted` is empty when every row hit ON CONFLICT DO NOTHING, which is
    -- the common case for an at-least-once client replaying a batch. Skipping
    -- the notify there keeps duplicate submissions from waking the analyser.
    IF EXISTS (SELECT 1 FROM inserted) THEN
        -- Empty payload, deliberately. The payload cap is 8000 bytes and event
        -- data routinely carries secrets, so nothing about the event travels
        -- on the channel. It also makes Postgres collapse repeated signals:
        -- identical (channel, payload) pairs raised in one transaction are
        -- delivered once, so a 200-event batch wakes the analyser once.
        PERFORM pg_notify('events_ingested', '');
    END IF;
    RETURN NULL;
END;
$$;

-- FOR EACH STATEMENT, not FOR EACH ROW: a row-level trigger would queue one
-- notification per event in a batch insert.
CREATE TRIGGER events_notify_ingest
    AFTER INSERT ON events
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT
    EXECUTE FUNCTION notify_events_ingested();
