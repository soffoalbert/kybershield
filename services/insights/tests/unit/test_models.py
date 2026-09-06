"""Response models and severity ordering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pycommon import Severity
from pydantic import ValidationError

from insights.models import AgentSummary, AlertListItem, Page, TimelineItem

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def make_alert_item(**overrides) -> AlertListItem:
    """One alerts-feed row, with every field populated."""
    fields = {
        "alert_id": "11111111-1111-1111-1111-111111111111",
        "agent_id": "agent-alpha",
        "event_id": "evt-1",
        "timestamp": NOW,
        "rule": "secret_file_access",
        "severity": Severity.HIGH,
        "summary": "read /app/.env",
    }
    return AlertListItem(**(fields | overrides))


class TestSeverityOrdering:
    def test_orders_low_below_medium_below_high_below_critical(self) -> None:
        """The ordering the Postgres enum encodes, mirrored in Python so
        max_severity means the same on both sides."""
        ranks = [severity.rank for severity in Severity]

        assert ranks == sorted(ranks)
        assert [severity.value for severity in Severity] == [
            "low",
            "medium",
            "high",
            "critical",
        ]

    def test_max_of_returns_critical_from_a_mixed_list(self) -> None:
        highest = Severity.max_of([Severity.LOW, Severity.CRITICAL, Severity.MEDIUM])

        assert highest is Severity.CRITICAL

    def test_max_of_returns_none_for_an_empty_list(self) -> None:
        """An agent with no alerts has no maximum, and null is the honest
        answer rather than defaulting to low."""
        assert Severity.max_of([]) is None

    def test_severity_serialises_to_its_string_value(self) -> None:
        """A dashboard consuming the JSON sees "high", not "Severity.HIGH"."""
        item = make_alert_item(severity=Severity.HIGH)

        assert item.model_dump(mode="json")["severity"] == "high"


class TestPage:
    def test_has_more_is_true_when_rows_remain(self) -> None:
        page = Page[str](items=["a", "b"], total=5, limit=2, offset=0)

        assert page.has_more is True

    def test_has_more_is_false_on_the_last_page(self) -> None:
        page = Page[str](items=["e"], total=5, limit=2, offset=4)

        assert page.has_more is False

    def test_has_more_is_false_for_an_empty_page(self) -> None:
        page = Page[str](items=[], total=0, limit=50, offset=0)

        assert page.has_more is False

    def test_serialises_items_total_limit_and_offset(self) -> None:
        page = Page[AlertListItem](items=[make_alert_item()], total=1, limit=50, offset=0)

        body = page.model_dump(mode="json")

        assert body["total"] == 1
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert body["items"][0]["alert_id"] == "11111111-1111-1111-1111-111111111111"

    def test_has_more_is_not_part_of_the_serialised_body(self) -> None:
        """It is a property, so a client computes it from total and offset."""
        page = Page[str](items=["a"], total=5, limit=2, offset=0)

        assert "has_more" not in page.model_dump()


class TestAgentSummary:
    def test_accepts_a_null_max_severity(self) -> None:
        summary = AgentSummary(
            agent_id="agent-alpha",
            window_start=NOW,
            window_end=NOW,
            total_alerts=0,
        )

        assert summary.max_severity is None

    def test_defaults_top_rules_to_an_empty_list(self) -> None:
        summary = AgentSummary(
            agent_id="agent-alpha",
            window_start=NOW,
            window_end=NOW,
            total_alerts=0,
        )

        assert summary.top_rules == []
        assert summary.severity_counts == {}
        assert summary.total_events == 0


class TestTimelineItem:
    def test_rejects_a_kind_outside_event_and_alert(self) -> None:
        """The Literal is the contract a dashboard switches on."""
        with pytest.raises(ValidationError):
            TimelineItem(
                timestamp=NOW,
                kind="something_else",
                reference_id="evt-1",
                brief="file_read: /app/.env",
            )

    def test_allows_severity_and_rule_to_be_absent_on_an_event(self) -> None:
        item = TimelineItem(
            timestamp=NOW,
            kind="event",
            reference_id="evt-1",
            brief="file_read: /app/.env",
        )

        assert item.severity is None
        assert item.rule is None

    def test_carries_severity_and_rule_on_an_alert(self) -> None:
        item = TimelineItem(
            timestamp=NOW,
            kind="alert",
            reference_id="11111111-1111-1111-1111-111111111111",
            brief="read /app/.env",
            severity=Severity.HIGH,
            rule="secret_file_access",
        )

        assert item.model_dump(mode="json")["severity"] == "high"
        assert item.rule == "secret_file_access"
