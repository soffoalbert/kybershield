"""The rule plugin contract.

A rule is a pure function from one event to zero or more alert drafts. Keeping
them independent means each is unit-testable in isolation with no database, and
adding a detection is one new file plus one registry entry.

Every rule is stateless: it sees one event and the config, never storage and
never history. That is what lets the engine run the whole set over a batch
without any per-agent bookkeeping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pycommon import AlertDraft, Event

if TYPE_CHECKING:
    from analyser.config import AnalyserConfig


@runtime_checkable
class Rule(Protocol):
    """A single detection."""

    #: Stable identifier written to `alerts.rule`. Renaming one resets its
    #: dedupe history, since dedupe is keyed on (event_id, rule).
    id: str

    #: One-line human description, surfaced by `GET /v1/rules`.
    description: str

    def evaluate(self, event: Event, config: AnalyserConfig) -> list[AlertDraft]:
        """Assess one event.

        Thresholds and allowlists arrive via `config` rather than being baked
        into the rule body, so an operator can tune a detection without a code
        change.

        Must be side-effect free and must not touch the database. Returning an
        empty list is the common case. Raising is tolerated by the engine,
        which logs and isolates the failure, but a rule that cannot parse a
        payload should return `[]` rather than raise.
        """
        ...
