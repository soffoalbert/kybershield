"""RapidSecretReadsRule.

The only stateful rule, so these tests focus on the window arithmetic and on
what the rule does and does not aggregate.
"""

from __future__ import annotations

import pytest


class TestRapidSecretReadsRule:
    def test_fires_when_threshold_is_reached(self) -> None:
        """Three sensitive reads inside 60s, with the threshold at 3, yields
        one high alert on the third."""
        pytest.skip("TODO: implement")

    def test_does_not_fire_below_threshold(self) -> None:
        """Two reads inside the window are silent."""
        pytest.skip("TODO: implement")

    def test_counts_the_triggering_event(self) -> None:
        """The count includes the event under evaluation, so two prior reads
        plus this one reaches a threshold of 3. An off-by-one here changes the
        rule's meaning entirely."""
        pytest.skip("TODO: implement")

    def test_excludes_reads_older_than_the_window(self) -> None:
        """A read 61 seconds before the trigger, with a 60s window, does not
        count."""
        pytest.skip("TODO: implement")

    def test_window_lower_bound_is_exclusive(self) -> None:
        """A read exactly 60s before the trigger falls outside `(before -
        within, before]`. Pinning the boundary keeps the semantics from
        drifting."""
        pytest.skip("TODO: implement")

    def test_window_upper_bound_is_inclusive(self) -> None:
        """A prior read sharing the trigger's timestamp counts."""
        pytest.skip("TODO: implement")

    def test_does_not_aggregate_across_agents(self) -> None:
        """Reads by agent-beta never contribute to agent-alpha's count.
        Cross-agent aggregation would make the rule fire on ordinary fleet-wide
        startup config loading."""
        pytest.skip("TODO: implement")

    def test_does_not_count_non_sensitive_reads(self) -> None:
        """Three reads of /etc/hosts are silent; volume alone is not the
        signal."""
        pytest.skip("TODO: implement")

    def test_ignores_non_file_read_event(self) -> None:
        pytest.skip("TODO: implement")

    def test_skips_lookback_for_non_sensitive_path(self) -> None:
        """A read of an ordinary file must not trigger a history query at all.
        The lookback is the rule's only cost and should be paid solely on
        events that could complete a burst."""
        pytest.skip("TODO: implement")

    def test_uses_occurred_at_not_received_at(self) -> None:
        """The window is over when the activity happened. Seed history whose
        received_at ordering contradicts its occurred_at ordering and assert
        the rule follows occurred_at."""
        pytest.skip("TODO: implement")

    def test_details_include_count_window_and_paths(self) -> None:
        """details carries the count, both window bounds, and the distinct
        paths, which is what makes the alert actionable."""
        pytest.skip("TODO: implement")

    def test_alert_attaches_to_the_triggering_event(self) -> None:
        """The draft's event_id is the burst's last event, not its first. That
        is what keeps re-analysis idempotent under UNIQUE (event_id, rule)."""
        pytest.skip("TODO: implement")

    def test_respects_configured_threshold(self) -> None:
        """With the threshold at 5, four reads stay silent."""
        pytest.skip("TODO: implement")

    def test_respects_configured_window(self) -> None:
        """With a 300s window, reads 120s apart still aggregate."""
        pytest.skip("TODO: implement")
