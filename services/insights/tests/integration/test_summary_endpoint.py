"""GET /v1/agents/{agent_id}/summary."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestTotals:
    def test_counts_alerts_in_the_window(self) -> None:
        pytest.skip("TODO: implement")

    def test_excludes_alerts_outside_the_window(self) -> None:
        pytest.skip("TODO: implement")

    def test_counts_only_the_requested_agent(self) -> None:
        pytest.skip("TODO: implement")

    def test_reports_total_events_alongside_total_alerts(self) -> None:
        """Alerts without a denominator are hard to read: ten alerts out of
        twelve events is a very different picture from ten out of ten
        thousand."""
        pytest.skip("TODO: implement")


class TestMaxSeverity:
    def test_reports_the_highest_severity_present(self) -> None:
        pytest.skip("TODO: implement")

    def test_is_null_when_the_agent_has_no_alerts(self) -> None:
        pytest.skip("TODO: implement")

    def test_ignores_a_higher_severity_outside_the_window(self) -> None:
        """The window applies to the maximum too, or a long-resolved critical
        would keep an agent looking dangerous forever."""
        pytest.skip("TODO: implement")


class TestTopRules:
    def test_orders_by_count_descending(self) -> None:
        pytest.skip("TODO: implement")

    def test_breaks_ties_by_rule_name(self) -> None:
        """Deterministic output, so the response is diffable across runs."""
        pytest.skip("TODO: implement")

    def test_caps_the_list_at_top_rules_limit(self) -> None:
        pytest.skip("TODO: implement")

    def test_is_empty_when_the_agent_has_no_alerts(self) -> None:
        pytest.skip("TODO: implement")


class TestSeverityCounts:
    def test_reports_a_count_per_severity_present(self) -> None:
        pytest.skip("TODO: implement")

    def test_omits_severities_with_no_alerts(self) -> None:
        pytest.skip("TODO: implement")

    def test_counts_sum_to_total_alerts(self) -> None:
        """An internal consistency check that catches a mis-scoped window in
        one of the two queries the summary runs."""
        pytest.skip("TODO: implement")


class TestWindowHandling:
    def test_defaults_to_24_hours(self) -> None:
        pytest.skip("TODO: implement")

    def test_accepts_a_window_shorthand(self) -> None:
        """window=7d widens the range."""
        pytest.skip("TODO: implement")

    def test_echoes_the_resolved_bounds(self) -> None:
        """window_start and window_end are returned, so a caller can tell
        exactly what was measured rather than inferring it."""
        pytest.skip("TODO: implement")

    def test_rejects_an_unparseable_window(self) -> None:
        pytest.skip("TODO: implement")


class TestUnknownAgent:
    def test_returns_a_zeroed_summary_rather_than_404(self) -> None:
        """A dashboard can render "quiet" instead of special-casing a missing
        response."""
        pytest.skip("TODO: implement")
