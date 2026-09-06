"""The analysis pipeline.

Splits cleanly into a pure part (`analyse_event`, one event through the rules,
no I/O) and an I/O part (`run_once`, `backfill`). Almost all the rule testing
targets the pure part.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from pycommon import AlertDraft, Event

from analyser.config import AnalyserConfig
from analyser.repository import AnalysisRepository
from analyser.rules import Rule

logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    """Outcome of one pass, returned by the API and printed by the CLI."""

    events_examined: int = 0
    alerts_generated: int = 0
    #: Written after deduplication. Lower than `alerts_generated` means the
    #: same events were analysed before.
    alerts_written: int = 0
    cursor_before: int = 0
    cursor_after: int = 0
    duration_ms: float = 0.0
    #: Rule ids that raised, with their error text. Non-empty means a rule bug.
    rule_failures: list[str] = field(default_factory=list)
    #: Set when the pass returned as many events as it asked for.
    batch_full: bool = False

    @property
    def has_more(self) -> bool:
        """True if the batch filled up, so another pass should run immediately.

        Keyed on the batch being full rather than on the cursor having moved:
        a short batch advances the cursor too, and treating that as "more"
        would cost an extra empty pass every time the analyser catches up.
        """
        return self.batch_full


class AnalysisEngine:
    """Runs the rule set over events and persists the resulting alerts."""

    def __init__(
        self,
        rules: Sequence[Rule],
        repo: AnalysisRepository,
        config: AnalyserConfig,
        batch_size: int = 200,
    ) -> None:
        """
        Args:
            rules: Detections to run, in order.
            repo: Storage access.
            config: Passed to every rule; holds the tunable thresholds.
            batch_size: Events claimed per pass.
        """
        self.rules = list(rules)
        self.repo = repo
        self.config = config
        self.batch_size = batch_size

    def analyse_event(self, event: Event) -> tuple[list[AlertDraft], list[str]]:
        """Run every rule against one event.

        Pure with respect to storage, so unit tests need no database.

        A rule that raises is caught, logged with its id and the event id, and
        recorded in the returned failure list; the remaining rules still run.
        One buggy detection must not stop the pipeline or block the cursor,
        which would halt analysis for every other rule too.

        @returns The drafts produced, and the ids of rules that raised.
        """
        drafts: list[AlertDraft] = []
        failures: list[str] = []
        for rule in self.rules:
            try:
                drafts.extend(rule.evaluate(event, self.config))
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                logger.exception(
                    "rule %s raised on event %s", rule.id, event.event_id
                )
                failures.append(f"{rule.id}: {exc}")
        return drafts, failures

    def _analyse_batch(self, events: Sequence[Event], report: RunReport) -> list[AlertDraft]:
        """Run the rules over `events`, accumulating failures into `report`."""
        drafts: list[AlertDraft] = []
        for event in events:
            event_drafts, failures = self.analyse_event(event)
            drafts.extend(event_drafts)
            report.rule_failures.extend(failures)
        return drafts

    def run_once(self, batch_size: int | None = None) -> RunReport:
        """Claim one batch past the cursor, analyse it, persist, advance.

        Returns an empty report with an unchanged cursor when there is nothing
        new, which is the steady state between agent activity.

        Alert inserts and the cursor update share a transaction, so a failure
        leaves the watermark where it was and the batch is retried.
        """
        limit = batch_size or self.batch_size
        started = time.perf_counter()

        # The cursor lives in the database, not on the engine: two analyser
        # processes must not each keep their own idea of the watermark.
        cursor = self.repo.get_cursor()
        report = RunReport(cursor_before=cursor, cursor_after=cursor)

        events = self.repo.fetch_batch_after(cursor, limit)
        if not events:
            report.duration_ms = (time.perf_counter() - started) * 1000
            return report

        drafts = self._analyse_batch(events, report)

        # The batch is ordered by ingest_seq, so the last row is its watermark.
        new_cursor = events[-1].ingest_seq
        report.alerts_written = self.repo.process_batch_atomically(events, drafts, new_cursor)

        report.events_examined = len(events)
        report.alerts_generated = len(drafts)
        report.cursor_after = new_cursor
        report.batch_full = len(events) == limit
        report.duration_ms = (time.perf_counter() - started) * 1000
        return report

    def run_until_caught_up(self, max_batches: int = 50) -> RunReport:
        """Repeat :meth:`run_once` until a batch comes back short.

        Bounded by `max_batches` so a large backlog cannot monopolise the
        poller thread indefinitely. Returns the aggregate report.
        """
        started = time.perf_counter()
        cursor = self.repo.get_cursor()
        total = RunReport(cursor_before=cursor, cursor_after=cursor)

        for _ in range(max_batches):
            report = self.run_once()
            total.events_examined += report.events_examined
            total.alerts_generated += report.alerts_generated
            total.alerts_written += report.alerts_written
            total.rule_failures.extend(report.rule_failures)
            total.cursor_after = report.cursor_after
            # Carried so the caller can tell "hit max_batches with work left"
            # from "genuinely caught up".
            total.batch_full = report.batch_full
            if not report.has_more:
                break

        total.duration_ms = (time.perf_counter() - started) * 1000
        return total

    def backfill(self, since: datetime | None = None) -> RunReport:
        """Re-run rules over historical events without touching the cursor.

        Safe to run at any time: the alert unique constraint means already
        known findings are skipped, so only genuinely new detections (from a
        new or newly tuned rule) get written. Leaving the cursor alone means a
        backfill cannot cause the live poller to skip fresh events.

        Args:
            since: Lower bound on `occurred_at`. `None` walks all history.
        """
        started = time.perf_counter()
        cursor = self.repo.get_cursor()
        # Reported unchanged on both sides, which is the point of a backfill.
        report = RunReport(cursor_before=cursor, cursor_after=cursor)

        offset = 0
        while True:
            events = self.repo.fetch_batch_since(since, self.batch_size, offset)
            if not events:
                break

            drafts = self._analyse_batch(events, report)
            # Plain insert, not process_batch_atomically: that call advances the
            # cursor, which a backfill must never do.
            report.alerts_written += self.repo.insert_alerts_ignore_dupes(drafts)
            report.events_examined += len(events)
            report.alerts_generated += len(drafts)

            if len(events) < self.batch_size:
                break
            offset += len(events)

        report.duration_ms = (time.perf_counter() - started) * 1000
        return report
