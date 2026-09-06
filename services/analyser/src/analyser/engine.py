"""The analysis pipeline.

Splits cleanly into a pure part (`analyse_event`, one event through the rules,
no I/O) and an I/O part (`run_once`, `backfill`). Almost all the rule testing
targets the pure part.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pycommon import AlertDraft, Event

from analyser.config import AnalyserConfig
from analyser.repository import AnalysisRepository
from analyser.rules import Rule


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

    @property
    def has_more(self) -> bool:
        """True if the batch filled up, so another pass should run immediately."""
        raise NotImplementedError


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
        raise NotImplementedError

    def analyse_event(self, event: Event) -> tuple[list[AlertDraft], list[str]]:
        """Run every rule against one event.

        Pure with respect to storage, so unit tests need no database.

        A rule that raises is caught, logged with its id and the event id, and
        recorded in the returned failure list; the remaining rules still run.
        One buggy detection must not stop the pipeline or block the cursor,
        which would halt analysis for every other rule too.

        @returns The drafts produced, and the ids of rules that raised.
        """
        raise NotImplementedError

    def run_once(self, batch_size: int | None = None) -> RunReport:
        """Claim one batch past the cursor, analyse it, persist, advance.

        Returns an empty report with an unchanged cursor when there is nothing
        new, which is the steady state between agent activity.

        Alert inserts and the cursor update share a transaction, so a failure
        leaves the watermark where it was and the batch is retried.
        """
        raise NotImplementedError

    def run_until_caught_up(self, max_batches: int = 50) -> RunReport:
        """Repeat :meth:`run_once` until a batch comes back short.

        Bounded by `max_batches` so a large backlog cannot monopolise the
        poller thread indefinitely. Returns the aggregate report.
        """
        raise NotImplementedError

    def backfill(self, since: datetime | None = None) -> RunReport:
        """Re-run rules over historical events without touching the cursor.

        Safe to run at any time: the alert unique constraint means already
        known findings are skipped, so only genuinely new detections (from a
        new or newly tuned rule) get written. Leaving the cursor alone means a
        backfill cannot cause the live poller to skip fresh events.
        """
        raise NotImplementedError
