"""AnalysisEngine, against an in-memory repository.

Covers rule orchestration and failure isolation. The transactional guarantees
are the integration suite's job, since they are properties of the database.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from analyser.engine import AnalysisEngine
from tests.conftest import (
    FIXED_NOW,
    BrokenRule,
    FakeAnalysisRepository,
    StubRule,
    make_config,
    make_engine,
    make_event,
    make_events,
)


class TestAnalyseEvent:
    def test_returns_empty_for_a_benign_event(self) -> None:
        engine = make_engine(StubRule("quiet", fires=False))

        drafts, failures = engine.analyse_event(make_event())

        assert drafts == []
        assert failures == []

    def test_returns_one_draft_when_one_rule_matches(self) -> None:
        engine = make_engine(StubRule("noisy"))

        drafts, failures = engine.analyse_event(make_event(event_id="evt-7"))

        assert [draft.rule for draft in drafts] == ["noisy"]
        assert drafts[0].event_id == "evt-7"
        assert failures == []

    def test_returns_a_draft_per_matching_rule(self) -> None:
        engine = make_engine(StubRule("first"), StubRule("second"))

        drafts, _ = engine.analyse_event(make_event())

        assert [draft.rule for draft in drafts] == ["first", "second"]

    def test_runs_every_rule_even_after_one_matches(self) -> None:
        later = StubRule("later")
        engine = make_engine(StubRule("earlier"), later)

        engine.analyse_event(make_event())

        assert len(later.seen) == 1

    def test_isolates_a_rule_that_raises(self) -> None:
        engine = make_engine(BrokenRule(), StubRule("healthy"))

        drafts, failures = engine.analyse_event(make_event())

        assert [draft.rule for draft in drafts] == ["healthy"]
        assert len(failures) == 1

    def test_reports_the_failing_rule_id(self) -> None:
        engine = make_engine(BrokenRule("misconfigured", message="bad regex"))

        _, failures = engine.analyse_event(make_event())

        assert failures == ["misconfigured: bad regex"]

    def test_performs_no_writes(self) -> None:
        engine = make_engine(StubRule("noisy"))

        engine.analyse_event(make_event())

        assert engine.repo.written == []
        assert engine.repo.cursor == 0

    def test_preserves_rule_registration_order(self) -> None:
        engine = make_engine(StubRule("a"), StubRule("b"), StubRule("c"))

        drafts, _ = engine.analyse_event(make_event())

        assert [draft.rule for draft in drafts] == ["a", "b", "c"]


class TestRunOnce:
    def test_processes_pending_events_and_writes_alerts(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(3))

        report = engine.run_once()

        assert report.events_examined == 3
        assert report.alerts_generated == 3
        assert report.alerts_written == 3
        assert [draft.event_id for draft in engine.repo.written] == [
            "evt-1",
            "evt-2",
            "evt-3",
        ]

    def test_advances_the_cursor_to_the_last_ingest_seq(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(3))

        report = engine.run_once()

        assert report.cursor_before == 0
        assert report.cursor_after == 3
        assert engine.repo.cursor == 3

    def test_is_a_no_op_when_nothing_is_pending(self) -> None:
        engine = make_engine(StubRule("noisy"))
        engine.repo.cursor = 9

        report = engine.run_once()

        assert report.events_examined == 0
        assert report.alerts_written == 0
        assert report.cursor_after == 9
        assert engine.repo.cursor == 9

    def test_does_not_advance_the_cursor_when_the_insert_fails(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(2))
        engine.repo.fail_on_insert = RuntimeError("deadlock detected")

        with pytest.raises(RuntimeError):
            engine.run_once()

        assert engine.repo.cursor == 0
        assert engine.repo.written == []

    def test_claims_at_most_batch_size_events(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(10), batch_size=4)

        report = engine.run_once()

        assert report.events_examined == 4
        assert report.cursor_after == 4

    def test_reports_generated_and_written_counts_separately(self) -> None:
        """A replayed event still generates drafts, but the dedupe writes none."""
        engine = make_engine(StubRule("noisy"), events=make_events(2))
        engine.run_once()
        engine.repo.cursor = 0

        report = engine.run_once()

        assert report.alerts_generated == 2
        assert report.alerts_written == 0

    def test_records_rule_failures_in_the_report(self) -> None:
        engine = make_engine(BrokenRule(), StubRule("healthy"), events=make_events(2))

        report = engine.run_once()

        assert report.rule_failures == ["broken: boom", "broken: boom"]

    def test_still_advances_the_cursor_when_a_rule_failed(self) -> None:
        """One buggy detection must not block analysis for every other rule."""
        engine = make_engine(BrokenRule(), StubRule("healthy"), events=make_events(2))

        report = engine.run_once()

        assert report.cursor_after == 2
        assert report.alerts_written == 2

    def test_has_more_is_true_when_the_batch_filled(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(4), batch_size=2)

        assert engine.run_once().has_more is True

    def test_has_more_is_false_when_the_batch_came_back_short(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(1), batch_size=2)

        assert engine.run_once().has_more is False


class TestRunUntilCaughtUp:
    def test_drains_a_multi_batch_backlog(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(10), batch_size=4)

        report = engine.run_until_caught_up()

        assert report.events_examined == 10
        assert report.cursor_after == 10
        assert engine.repo.cursor == 10

    def test_stops_at_max_batches(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(10), batch_size=2)

        report = engine.run_until_caught_up(max_batches=3)

        assert report.events_examined == 6
        # Left full, so the caller can tell this from "genuinely caught up".
        assert report.has_more is True

    def test_aggregates_counts_across_batches(self) -> None:
        engine = make_engine(StubRule("a"), StubRule("b"), events=make_events(5), batch_size=2)

        report = engine.run_until_caught_up()

        assert report.alerts_generated == 10
        assert report.alerts_written == 10
        assert report.cursor_before == 0


class TestBackfill:
    def test_reanalyses_historical_events(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(3))

        report = engine.backfill()

        assert report.events_examined == 3
        assert report.alerts_written == 3

    def test_leaves_the_live_cursor_untouched(self) -> None:
        """A backfill that moved the cursor would make the poller skip events."""
        engine = make_engine(StubRule("noisy"), events=make_events(3))
        engine.repo.cursor = 1

        report = engine.backfill()

        assert engine.repo.cursor == 1
        assert report.cursor_before == 1
        assert report.cursor_after == 1

    def test_filters_by_since(self) -> None:
        old = make_event(event_id="old", ingest_seq=1, occurred_at=FIXED_NOW - timedelta(days=2))
        recent = make_event(event_id="recent", ingest_seq=2, occurred_at=FIXED_NOW)
        engine = make_engine(StubRule("noisy"), events=[old, recent])

        report = engine.backfill(since=FIXED_NOW - timedelta(hours=1))

        assert report.events_examined == 1
        assert [draft.event_id for draft in engine.repo.written] == ["recent"]

    def test_writes_nothing_when_findings_already_exist(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(3))
        engine.backfill()

        report = engine.backfill()

        assert report.alerts_generated == 3
        assert report.alerts_written == 0

    def test_writes_only_findings_from_a_newly_added_rule(self) -> None:
        """The point of a backfill: an existing rule's findings are skipped."""
        events = make_events(3)
        repo = FakeAnalysisRepository(events)
        AnalysisEngine([StubRule("old")], repo, make_config()).backfill()

        report = AnalysisEngine([StubRule("old"), StubRule("new")], repo, make_config()).backfill()

        assert report.alerts_written == 3
        assert {draft.rule for draft in repo.written} == {"old", "new"}

    def test_pages_through_history_beyond_one_batch(self) -> None:
        engine = make_engine(StubRule("noisy"), events=make_events(7), batch_size=3)

        report = engine.backfill()

        assert report.events_examined == 7
        assert report.alerts_written == 7
