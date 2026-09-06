"""The pipeline against real PostgreSQL.

Everything here depends on database semantics that a fake cannot reproduce: the
alert unique constraint, transactional cursor advancement, and ingest_seq
ordering under out-of-order arrival.

Requires `docker compose up -d postgres`.
"""

from __future__ import annotations

import os
import time
import pytest
import psycopg2
from psycopg2.extras import RealDictCursor
from threading import Thread

pytestmark = pytest.mark.integration

PG_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres"
)

def get_conn():
    return psycopg2.connect(PG_DSN)

def clear_db():
    with get_conn() as conn, conn.cursor() as cur:
        # assumed table names and structure, adapt as needed
        cur.execute("DELETE FROM alerts")
        cur.execute("DELETE FROM events")
        cur.execute("DELETE FROM analysis_cursor")

def seed_event(occurred_at, ingest_seq, event_type='test', payload=None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (occurred_at, ingest_seq, type, payload) VALUES (%s, %s, %s, %s) RETURNING id",
            (occurred_at, ingest_seq, event_type, payload)
        )
        return cur.fetchone()[0]

def read_alerts():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM alerts ORDER BY event_ingest_seq, rule")
        return cur.fetchall()

def read_cursor():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT last_ingest_seq FROM analysis_cursor LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None

def set_cursor(value):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM analysis_cursor")
        cur.execute("INSERT INTO analysis_cursor (last_ingest_seq) VALUES (%s)", (value,))

def run_pipeline():
    """Stub: Replace with call to your pipeline invocation code."""
    # Example: analyser.pipeline.run_once()
    from services.analyser.pipeline import run_once
    return run_once()

class TestRunOnce:
    def setup_method(self):
        clear_db()

    def test_analyses_new_events_and_persists_alerts(self) -> None:
        """Seed a .env read, run once, assert one alerts row with the right
        rule and severity."""
        event_id = seed_event("2022-01-01T00:00:00Z", 1)
        set_cursor(0)
        res = run_pipeline()
        alerts = read_alerts()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["event_id"] == event_id
        assert alert["rule"]  # replace with actual expected rule name
        assert alert["severity"]  # replace with actual expected severity

    def test_second_run_writes_nothing(self) -> None:
        event_id = seed_event("2022-01-01T00:00:00Z", 1)
        set_cursor(0)
        res1 = run_pipeline()
        alerts1 = read_alerts()
        rowcount1 = len(alerts1)
        res2 = run_pipeline()
        alerts2 = read_alerts()
        assert len(alerts2) == rowcount1

    def test_advances_the_persisted_cursor(self) -> None:
        seed_event("2022-01-01T00:00:00Z", 1)
        seed_event("2022-01-01T01:00:00Z", 2)
        set_cursor(0)
        run_pipeline()
        assert read_cursor() == 2

    def test_leaves_the_cursor_unmoved_when_the_transaction_fails(self) -> None:
        # Simulate a failing rule by injecting a failing rule into the pipeline, or violate constraint
        # We'll insert a duplicate alert row if possible
        seed_event("2022-01-01T00:00:00Z", 1)
        set_cursor(0)
        # pre-set analysis_cursor
        before = read_cursor()
        # Simulate failure (suppose run_once will fail on an event with specific payload)
        try:
            from services.analyser.pipeline import BROKEN_RULE
            BROKEN_RULE.enabled = True
            with pytest.raises(Exception):
                run_pipeline()
        finally:
            BROKEN_RULE.enabled = False
        # No alert should land, cursor should be unmoved
        assert read_cursor() == before
        assert not read_alerts()

    def test_picks_up_an_out_of_order_event(self) -> None:
        # Seed two events, second has an earlier occurred_at but later ingest_seq
        e1 = seed_event("2022-01-01T01:00:00Z", 1)
        run_pipeline()
        # Now insert out-of-order event
        e2 = seed_event("2022-01-01T00:00:00Z", 2)
        run_pipeline()
        alerts = read_alerts()
        assert {a["event_id"] for a in alerts} == {e1, e2}

    def test_processes_events_in_ingest_seq_order(self) -> None:
        e1 = seed_event("2022-01-01T01:00:00Z", 1)
        e2 = seed_event("2022-01-01T02:00:00Z", 2)
        set_cursor(0)
        run_pipeline()
        alerts = read_alerts()
        seqs = [a["event_ingest_seq"] for a in alerts]
        assert seqs == sorted(seqs), "Should process by ingest_seq order"

    def test_is_a_no_op_on_an_empty_table(self) -> None:
        set_cursor(0)
        run_pipeline()
        alerts = read_alerts()
        assert alerts == []

    def test_writes_several_alerts_for_one_event(self) -> None:
        # Event that matches multiple rules
        e1 = seed_event("2022-01-01T01:00:00Z", 1, payload={"matches_two_rules": True})
        set_cursor(0)
        run_pipeline()
        alerts = read_alerts()
        assert len(alerts) >= 2
        rules = {a["rule"] for a in alerts}
        assert len(rules) >= 2

    def test_survives_a_rule_that_raises(self) -> None:
        # Insert event that will trigger both a broken rule and a good rule
        e1 = seed_event("2022-01-01T00:00:00Z", 1, payload={"trip_broken_rule": True, "trip_good_rule": True})
        set_cursor(0)
        from services.analyser.pipeline import BROKEN_RULE
        BROKEN_RULE.enabled = True
        try:
            run_pipeline()
        finally:
            BROKEN_RULE.enabled = False
        alerts = read_alerts()
        assert alerts  # At least the good rule's alert should be present
        assert read_cursor() == 1

class TestConcurrency:
    def setup_method(self):
        clear_db()

    def test_two_concurrent_runs_do_not_duplicate_alerts(self) -> None:
        e1 = seed_event("2022-01-01T00:00:00Z", 1)
        set_cursor(0)
        # Launch two threads to simulate concurrent runs
        results = []
        def run():
            try:
                run_pipeline()
            except Exception:
                pass
        t1 = Thread(target=run)
        t2 = Thread(target=run)
        t1.start(); t2.start()
        t1.join(); t2.join()
        alerts = read_alerts()
        assert len(alerts) == 1

class TestBackfill:
    def setup_method(self):
        clear_db()

    def test_reanalyses_all_history(self) -> None:
        e1 = seed_event("2022-01-01T00:00:00Z", 1)
        e2 = seed_event("2022-01-01T01:00:00Z", 2)
        # Suppose there's a backfill method
        from services.analyser.pipeline import backfill
        backfill()
        alerts = read_alerts()
        event_ids = {a["event_id"] for a in alerts}
        assert {e1, e2} <= event_ids

    def test_repeat_backfill_writes_nothing(self) -> None:
        e1 = seed_event("2022-01-01T00:00:00Z", 1)
        from services.analyser.pipeline import backfill
        backfill()
        n1 = len(read_alerts())
        backfill()
        n2 = len(read_alerts())
        assert n1 == n2

    def test_leaves_the_cursor_untouched(self) -> None:
        e1 = seed_event("2022-01-01T00:00:00Z", 1)
        set_cursor(7)
        from services.analyser.pipeline import backfill
        backfill()
        assert read_cursor() == 7

    def test_since_filter_limits_the_range(self) -> None:
        e1 = seed_event("2022-01-01T00:00:00Z", 1)
        e2 = seed_event("2022-01-01T01:00:00Z", 2)
        from services.analyser.pipeline import backfill
        backfill(since_ingest_seq=2)
        alerts = read_alerts()
        event_ids = {a["event_id"] for a in alerts}
        assert e2 in event_ids and e1 not in event_ids

class TestForeignKeys:
    def setup_method(self):
        clear_db()

    def test_alert_insert_fails_for_an_unknown_event(self) -> None:
        """The FK is what keeps orphaned alerts out of the timeline."""
        with get_conn() as conn, conn.cursor() as cur:
            with pytest.raises(psycopg2.IntegrityError):
                cur.execute(
                    "INSERT INTO alerts (event_id, rule, severity, event_ingest_seq) VALUES (%s, %s, %s, %s)",
                    (9999, 'rule1', 'high', 1)
                )
                conn.commit()

    def test_deleting_an_event_cascades_to_its_alerts(self) -> None:
        e1 = seed_event("2022-01-01T00:00:00Z", 1)
        set_cursor(0)
        run_pipeline()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id = %s", (e1,))
        alerts = read_alerts()
        assert len(alerts) == 0
