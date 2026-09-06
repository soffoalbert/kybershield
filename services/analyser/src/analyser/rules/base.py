"""The rule plugin contract.

A rule is a small, pure-ish function from one event to zero or more alert
drafts. Keeping them independent means each is unit-testable in isolation with
no database, and adding a detection is one new file plus one registry entry.

The one rule that genuinely needs history (rapid repeated reads) gets it
through :class:`RuleContext` rather than reaching for a connection itself, so
the rules stay ignorant of storage.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pycommon import AlertDraft, Event

if TYPE_CHECKING:
    from analyser.config import AnalyserConfig


class RuleContext(Protocol):
    """Everything a rule may read beyond the event itself."""

    config: AnalyserConfig

    def recent_events_for_agent(
        self,
        agent_id: str,
        type_: str,
        within: timedelta,
        before: object,
    ) -> list[Event]:
        """Return the agent's events of `type_` in the window ending at `before`.

        The window is `(before - within, before]`, ordered oldest first, and is
        expressed over `occurred_at` rather than `ingest_seq` because "three
        reads in a minute" is a claim about when things happened, not when they
        arrived.

        Args:
            agent_id: Agent to look back over.
            type_: Event type filter, e.g. `file_read`.
            within: Window length.
            before: Upper bound, a timezone-aware datetime, normally the
                triggering event's `occurred_at`.
        """
        ...


@runtime_checkable
class Rule(Protocol):
    """A single detection."""

    #: Stable identifier written to `alerts.rule`. Renaming one resets its
    #: dedupe history, since dedupe is keyed on (event_id, rule).
    id: str

    #: One-line human description, surfaced by `GET /v1/rules`.
    description: str

    def evaluate(self, event: Event, ctx: RuleContext) -> list[AlertDraft]:
        """Assess one event.

        Must be side-effect free and must not write to the database. Returning
        an empty list is the common case. Raising is tolerated by the engine,
        which logs and isolates the failure, but a rule that cannot parse a
        payload should return `[]` rather than raise.
        """
        ...
