"""The pipeline against real PostgreSQL.

Everything here depends on database semantics that a fake cannot reproduce: the
alert unique constraint, transactional cursor advancement, and ingest_seq
ordering under out-of-order arrival.

Requires `docker compose up -d postgres`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestRunOnce:
    def test_analyses_new_events_and_persists_alerts(self) -> None:
        """Seed a .env read, run once, assert one alerts row with the right
        rule and severity."""
        pytest.skip("TODO: implement")

    def test_second_run_writes_nothing(self) -> None:
        """The dedupe requirement, stated end to end. Reset the cursor, run
        again, and assert alerts_written is 0 while the row count is
        unchanged."""
        pytest.skip("TODO: implement")

    def test_advances_the_persisted_cursor(self) -> None:
        """analysis_cursor.last_ingest_seq equals the batch's highest
        ingest_seq after the run."""
        pytest.skip("TODO: implement")

    def test_leaves_the_cursor_unmoved_when_the_transaction_fails(self) -> None:
        """Force a failure mid-insert and assert both that no alerts landed and
        that the cursor is where it started, so the batch is retried."""
        pytest.skip("TODO: implement")

    def test_picks_up_an_out_of_order_event(self) -> None:
        """Insert an event whose occurred_at predates everything already
        analysed. Because it has a higher ingest_seq it is still past the
        cursor and gets analysed. This is the whole reason the cursor is a
        sequence and not a timestamp, and would fail under a timestamp
        watermark."""
        pytest.skip("TODO: implement")

    def test_processes_events_in_ingest_seq_order(self) -> None:
        pytest.skip("TODO: implement")

    def test_is_a_no_op_on_an_empty_table(self) -> None:
        pytest.skip("TODO: implement")

    def test_writes_several_alerts_for_one_event(self) -> None:
        """An event tripping two rules produces two rows, distinguished by the
        rule column, which the unique constraint permits."""
        pytest.skip("TODO: implement")

    def test_survives_a_rule_that_raises(self) -> None:
        """Register a deliberately broken rule and assert the other rules'
        alerts still commit and the cursor still advances."""
        pytest.skip("TODO: implement")


class TestConcurrency:
    def test_two_concurrent_runs_do_not_duplicate_alerts(self) -> None:
        """The unique constraint absorbs the race, so a second analyser
        instance is safe even though nothing coordinates them."""
        pytest.skip("TODO: implement")


class TestBackfill:
    def test_reanalyses_all_history(self) -> None:
        pytest.skip("TODO: implement")

    def test_repeat_backfill_writes_nothing(self) -> None:
        pytest.skip("TODO: implement")

    def test_leaves_the_cursor_untouched(self) -> None:
        pytest.skip("TODO: implement")

    def test_since_filter_limits_the_range(self) -> None:
        pytest.skip("TODO: implement")


class TestForeignKeys:
    def test_alert_insert_fails_for_an_unknown_event(self) -> None:
        """The FK is what keeps orphaned alerts out of the timeline."""
        pytest.skip("TODO: implement")

    def test_deleting_an_event_cascades_to_its_alerts(self) -> None:
        pytest.skip("TODO: implement")
