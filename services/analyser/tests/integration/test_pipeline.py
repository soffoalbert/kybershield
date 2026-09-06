"""The pipeline against real PostgreSQL.

Everything here depends on database semantics that a fake cannot reproduce: the
alert unique constraint, transactional cursor advancement, and ingest_seq
ordering under out-of-order arrival.

Requires `docker compose up -d postgres`.
"""

from __future__ import annotations

from datetime import timedelta
from threading import Thread

import psycopg
import pytest
from pycommon import AlertDraft, Database, Severity

from analyser.engine import AnalysisEngine
from tests.conftest import FIXED_NOW, BrokenRule, StubRule
from tests.integration.conftest import (
    read_alerts,
    read_cursor,
    seed_event,
    seed_secret_read,
    set_cursor,
)

pytestmark = pytest.mark.integration


class TestRunOnce:
    def test_analyses_new_events_and_persists_alerts(
        self, db: Database, engine: AnalysisEngine
    ) -> None:
        seed_secret_read(db, event_id="evt-1")

        report = engine.run_once()

        alerts = read_alerts(db)
        assert report.alerts_written == 1
        assert [(alert.event_id, alert.rule) for alert in alerts] == [
            ("evt-1", "secret_file_access")
        ]
        assert alerts[0].severity == Severity.HIGH

    def test_second_run_writes_nothing(self, db: Database, engine: AnalysisEngine) -> None:
        """The cursor has moved past the batch, so there is nothing to claim."""
        seed_secret_read(db)
        engine.run_once()

        report = engine.run_once()

        assert report.events_examined == 0
        assert len(read_alerts(db)) == 1

    def test_rewinding_the_cursor_does_not_duplicate_alerts(
        self, db: Database, engine: AnalysisEngine
    ) -> None:
        """The (event_id, rule) constraint is what makes re-analysis safe."""
        seed_secret_read(db)
        engine.run_once()
        set_cursor(db, 0)

        report = engine.run_once()

        assert report.alerts_generated == 1
        assert report.alerts_written == 0
        assert len(read_alerts(db)) == 1

    def test_advances_the_persisted_cursor(self, db: Database, engine: AnalysisEngine) -> None:
        seed_secret_read(db, event_id="evt-1")
        last_seq = seed_secret_read(db, event_id="evt-2")

        engine.run_once()

        assert read_cursor(db) == last_seq

    def test_leaves_the_cursor_unmoved_when_the_transaction_fails(
        self, db: Database, make_engine
    ) -> None:
        """Alert inserts and the cursor update share one transaction.

        Forced with a draft referencing an event that does not exist, which the
        alerts foreign key rejects.
        """
        seed_secret_read(db)
        engine = make_engine(OrphanDraftRule())

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            engine.run_once()

        assert read_cursor(db) == 0
        assert read_alerts(db) == []

    def test_picks_up_an_out_of_order_event(self, db: Database, engine: AnalysisEngine) -> None:
        """A late event carries an old timestamp but a fresh ingest_seq."""
        seed_secret_read(db, event_id="recent", occurred_at=FIXED_NOW)
        engine.run_once()

        seed_secret_read(db, event_id="late", occurred_at=FIXED_NOW - timedelta(days=1))
        report = engine.run_once()

        assert report.events_examined == 1
        assert {alert.event_id for alert in read_alerts(db)} == {"recent", "late"}

    def test_processes_events_in_ingest_seq_order(
        self, db: Database, make_engine
    ) -> None:
        recorder = StubRule("recorder", fires=False)
        seed_event(db, event_id="evt-1")
        seed_event(db, event_id="evt-2")
        seed_event(db, event_id="evt-3")

        make_engine(recorder).run_once()

        assert [event.event_id for event in recorder.seen] == ["evt-1", "evt-2", "evt-3"]

    def test_is_a_no_op_on_an_empty_table(self, db: Database, engine: AnalysisEngine) -> None:
        report = engine.run_once()

        assert report.events_examined == 0
        assert read_cursor(db) == 0

    def test_writes_several_alerts_for_one_event(self, db: Database, make_engine) -> None:
        seed_event(db, event_id="evt-1")

        make_engine(StubRule("first"), StubRule("second")).run_once()

        assert [alert.rule for alert in read_alerts(db)] == ["first", "second"]

    def test_survives_a_rule_that_raises(self, db: Database, make_engine) -> None:
        seed_secret_read(db)
        engine = make_engine(BrokenRule(), StubRule("healthy"))

        report = engine.run_once()

        assert report.rule_failures == ["broken: boom"]
        assert [alert.rule for alert in read_alerts(db)] == ["healthy"]
        assert read_cursor(db) == 1

    def test_claims_events_in_batches(self, db: Database, make_engine) -> None:
        for seq in range(1, 6):
            seed_secret_read(db, event_id=f"evt-{seq}")
        engine = make_engine(batch_size=2)

        first = engine.run_once()

        assert first.events_examined == 2
        assert first.has_more is True
        assert read_cursor(db) == 2


class TestConcurrency:
    def test_two_concurrent_runs_do_not_duplicate_alerts(
        self, db: Database, make_engine
    ) -> None:
        """Both passes may claim the batch; the constraint keeps one alert."""
        seed_secret_read(db)
        engines = [make_engine(), make_engine()]

        threads = [Thread(target=engine.run_once) for engine in engines]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(read_alerts(db)) == 1
        assert read_cursor(db) == 1


class TestBackfill:
    def test_reanalyses_all_history(self, db: Database, engine: AnalysisEngine) -> None:
        seed_secret_read(db, event_id="evt-1")
        seed_secret_read(db, event_id="evt-2")

        report = engine.backfill()

        assert report.alerts_written == 2
        assert {alert.event_id for alert in read_alerts(db)} == {"evt-1", "evt-2"}

    def test_repeat_backfill_writes_nothing(self, db: Database, engine: AnalysisEngine) -> None:
        seed_secret_read(db)
        engine.backfill()

        report = engine.backfill()

        assert report.alerts_generated == 1
        assert report.alerts_written == 0

    def test_leaves_the_cursor_untouched(self, db: Database, engine: AnalysisEngine) -> None:
        """A backfill that moved the cursor would make the poller skip events."""
        seed_secret_read(db)
        set_cursor(db, 7)

        engine.backfill()

        assert read_cursor(db) == 7

    def test_since_filter_limits_the_range(self, db: Database, engine: AnalysisEngine) -> None:
        seed_secret_read(db, event_id="old", occurred_at=FIXED_NOW - timedelta(days=2))
        seed_secret_read(db, event_id="recent", occurred_at=FIXED_NOW)

        engine.backfill(since=FIXED_NOW - timedelta(hours=1))

        assert [alert.event_id for alert in read_alerts(db)] == ["recent"]

    def test_writes_only_findings_from_a_newly_added_rule(
        self, db: Database, make_engine
    ) -> None:
        seed_secret_read(db)
        make_engine(StubRule("old")).backfill()

        report = make_engine(StubRule("old"), StubRule("new")).backfill()

        assert report.alerts_written == 1
        assert [alert.rule for alert in read_alerts(db)] == ["new", "old"]

    def test_pages_through_history_beyond_one_batch(
        self, db: Database, make_engine
    ) -> None:
        for seq in range(1, 6):
            seed_secret_read(db, event_id=f"evt-{seq}")

        report = make_engine(batch_size=2).backfill()

        assert report.events_examined == 5
        assert report.alerts_written == 5


class TestForeignKeys:
    def test_alert_insert_fails_for_an_unknown_event(self, db: Database) -> None:
        """The FK is what keeps orphaned alerts out of the timeline."""
        with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO alerts (event_id, agent_id, rule, severity, summary)
                VALUES ('no-such-event', 'agent-alpha', 'rule', 'high', 'orphan')
                """
            )

    def test_deleting_an_event_cascades_to_its_alerts(
        self, db: Database, engine: AnalysisEngine
    ) -> None:
        seed_secret_read(db, event_id="evt-1")
        engine.run_once()

        with db.transaction() as cur:
            cur.execute("DELETE FROM events WHERE event_id = 'evt-1'")

        assert read_alerts(db) == []


class OrphanDraftRule:
    """Emits a draft for an event that does not exist, to fail the insert."""

    id = "orphan"
    description = "test double"

    def evaluate(self, event, config) -> list[AlertDraft]:
        return [
            AlertDraft(
                event_id="no-such-event",
                agent_id=event.agent_id,
                rule=self.id,
                severity=Severity.LOW,
                summary="orphan",
            )
        ]
