"""Response models and severity ordering."""

from __future__ import annotations

import pytest


class TestSeverityOrdering:
    def test_orders_low_below_medium_below_high_below_critical(self) -> None:
        """The ordering the Postgres enum encodes, mirrored in Python so
        max_severity means the same on both sides."""
        pytest.skip("TODO: implement")

    def test_max_of_returns_critical_from_a_mixed_list(self) -> None:
        pytest.skip("TODO: implement")

    def test_max_of_returns_none_for_an_empty_list(self) -> None:
        """An agent with no alerts has no maximum, and null is the honest
        answer rather than defaulting to low."""
        pytest.skip("TODO: implement")

    def test_severity_serialises_to_its_string_value(self) -> None:
        """A dashboard consuming the JSON sees "high", not "Severity.HIGH"."""
        pytest.skip("TODO: implement")


class TestPage:
    def test_has_more_is_true_when_rows_remain(self) -> None:
        pytest.skip("TODO: implement")

    def test_has_more_is_false_on_the_last_page(self) -> None:
        pytest.skip("TODO: implement")

    def test_has_more_is_false_for_an_empty_page(self) -> None:
        pytest.skip("TODO: implement")

    def test_serialises_items_total_limit_and_offset(self) -> None:
        pytest.skip("TODO: implement")


class TestAgentSummary:
    def test_accepts_a_null_max_severity(self) -> None:
        pytest.skip("TODO: implement")

    def test_defaults_top_rules_to_an_empty_list(self) -> None:
        pytest.skip("TODO: implement")


class TestTimelineItem:
    def test_rejects_a_kind_outside_event_and_alert(self) -> None:
        """The Literal is the contract a dashboard switches on."""
        pytest.skip("TODO: implement")

    def test_allows_severity_and_rule_to_be_absent_on_an_event(self) -> None:
        pytest.skip("TODO: implement")
