"""Detects an agent reading sensitive files in rapid succession."""

from __future__ import annotations

from pycommon import AlertDraft, Event, Severity

from analyser.rules.base import RuleContext


class RapidSecretReadsRule:
    """Flags bursts of sensitive `file_read` events from one agent.

    The only stateful rule in the set: it fires when an agent reads at least
    `rapid_read_threshold` credential-bearing files within
    `rapid_read_window_seconds`. A single secret read is often legitimate
    configuration loading; sweeping several in a minute is enumeration.

    Two consequences worth noting in the write-up:

    - The lookback runs over `occurred_at`, not `ingest_seq`, because the claim
      is about when things happened. Out-of-order arrival therefore means a
      burst may only become visible once its last member arrives.
    - The alert is attached to the event that completed the burst, so
      re-analysing that event is still idempotent under the
      `UNIQUE (event_id, rule)` constraint.
    """

    id = "rapid_secret_reads"
    description = "Several sensitive file reads by one agent inside a short window"

    def evaluate(self, event: Event, ctx: RuleContext) -> list[AlertDraft]:
        """Return one alert if this read completes a burst.

        Ignores non-`file_read` events and reads of paths that are not
        sensitive, so the lookback is only paid for on an event that could
        complete a burst.

        Counts the triggering event plus prior sensitive reads by the same
        agent in `(occurred_at - window, occurred_at]`. Fires when the total
        reaches the threshold. `details` carries the count, the window bounds,
        and the distinct paths involved, which is what makes the alert
        actionable rather than just a number.
        """
        raise NotImplementedError
