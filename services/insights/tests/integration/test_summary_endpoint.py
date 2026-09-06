"""GET /v1/agents/{agent_id}/summary."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pycommon import Database, Severity

from tests.conftest import seed_alert, seed_event

pytestmark = pytest.mark.integration


def get_summary(client: TestClient, agent_id: str = "agent-alpha", **params: Any) -> dict[str, Any]:
    """Call the endpoint, assert it answered 200, and return the body."""
    response = client.get(f"/v1/agents/{agent_id}/summary", params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestTotals:
    def test_counts_alerts_in_the_window(self, client: TestClient, seeded: dict[str, Any]) -> None:
        assert get_summary(client, seeded["alpha"])["total_alerts"] == 3

    def test_excludes_alerts_outside_the_window(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        seed_alert(db, created_at=now - timedelta(hours=1))
        seed_alert(db, created_at=now - timedelta(hours=25))

        assert get_summary(client)["total_alerts"] == 1

    def test_counts_only_the_requested_agent(
        self, client: TestClient, seeded: dict[str, Any]
    ) -> None:
        assert get_summary(client, seeded["beta"])["total_alerts"] == 1

    def test_reports_total_events_alongside_total_alerts(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """Alerts without a denominator are hard to read: ten alerts out of
        twelve events is a very different picture from ten out of ten
        thousand."""
        events = [seed_event(db, occurred_at=now - timedelta(minutes=index)) for index in range(4)]
        seed_alert(db, event_id=events[0], created_at=now - timedelta(minutes=1))

        body = get_summary(client)

        assert body["total_events"] == 4
        assert body["total_alerts"] == 1

    def test_counts_events_only_inside_the_window(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        seed_event(db, occurred_at=now - timedelta(hours=1))
        seed_event(db, occurred_at=now - timedelta(hours=30))

        assert get_summary(client)["total_events"] == 1


class TestMaxSeverity:
    def test_reports_the_highest_severity_present(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        for severity in (Severity.LOW, Severity.CRITICAL, Severity.MEDIUM):
            seed_alert(db, severity=severity, created_at=now - timedelta(hours=1))

        assert get_summary(client)["max_severity"] == "critical"

    def test_is_null_when_the_agent_has_no_alerts(self, client: TestClient) -> None:
        assert get_summary(client)["max_severity"] is None

    def test_ignores_a_higher_severity_outside_the_window(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """The window applies to the maximum too, or a long-resolved critical
        would keep an agent looking dangerous forever."""
        seed_alert(db, severity=Severity.CRITICAL, created_at=now - timedelta(hours=25))
        seed_alert(db, severity=Severity.MEDIUM, created_at=now - timedelta(hours=1))

        assert get_summary(client)["max_severity"] == "medium"


class TestTopRules:
    def test_orders_by_count_descending(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        for _ in range(3):
            seed_alert(db, rule="domain_allowlist", created_at=now - timedelta(hours=1))
        for _ in range(2):
            seed_alert(db, rule="secret_file_access", created_at=now - timedelta(hours=1))

        assert get_summary(client)["top_rules"] == [
            {"rule": "domain_allowlist", "count": 3},
            {"rule": "secret_file_access", "count": 2},
        ]

    def test_breaks_ties_by_rule_name(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """Deterministic output, so the response is diffable across runs."""
        for rule in ("secret_file_access", "download_and_execute", "domain_allowlist"):
            seed_alert(db, rule=rule, created_at=now - timedelta(hours=1))

        assert [entry["rule"] for entry in get_summary(client)["top_rules"]] == [
            "domain_allowlist",
            "download_and_execute",
            "secret_file_access",
        ]

    def test_caps_the_list_at_top_rules_limit(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        limit = client.app.state.config.top_rules_limit
        for index in range(limit + 2):
            seed_alert(db, rule=f"rule_{index}", created_at=now - timedelta(hours=1))

        assert len(get_summary(client)["top_rules"]) == limit

    def test_is_empty_when_the_agent_has_no_alerts(self, client: TestClient) -> None:
        assert get_summary(client)["top_rules"] == []


class TestSeverityCounts:
    def test_reports_a_count_per_severity_present(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        for severity in (Severity.HIGH, Severity.HIGH, Severity.LOW):
            seed_alert(db, severity=severity, created_at=now - timedelta(hours=1))

        assert get_summary(client)["severity_counts"] == {"high": 2, "low": 1}

    def test_omits_severities_with_no_alerts(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        seed_alert(db, severity=Severity.MEDIUM, created_at=now - timedelta(hours=1))

        assert get_summary(client)["severity_counts"] == {"medium": 1}

    def test_is_empty_when_the_agent_has_no_alerts(self, client: TestClient) -> None:
        assert get_summary(client)["severity_counts"] == {}

    def test_counts_sum_to_total_alerts(self, client: TestClient, seeded: dict[str, Any]) -> None:
        """An internal consistency check that catches a mis-scoped window in
        one of the two queries the summary runs."""
        body = get_summary(client, seeded["alpha"])

        assert sum(body["severity_counts"].values()) == body["total_alerts"]


class TestWindowHandling:
    def test_defaults_to_24_hours(
        self, client: TestClient, seeded: dict[str, Any], now: datetime
    ) -> None:
        body = get_summary(client, seeded["alpha"])

        window_start = datetime.fromisoformat(body["window_start"])
        assert body["total_alerts"] == 3
        assert abs((now - timedelta(hours=24)) - window_start) < timedelta(minutes=1)

    def test_accepts_a_window_shorthand(self, client: TestClient, seeded: dict[str, Any]) -> None:
        """window=7d widens the range."""
        body = get_summary(client, seeded["alpha"], window="7d")

        assert body["total_alerts"] == 4
        assert body["max_severity"] == "critical"

    def test_echoes_the_resolved_bounds(self, client: TestClient, now: datetime) -> None:
        """window_start and window_end are returned, so a caller can tell
        exactly what was measured rather than inferring it."""
        since = now - timedelta(hours=6)
        until = now - timedelta(hours=2)

        body = get_summary(client, since=since.isoformat(), until=until.isoformat())

        assert datetime.fromisoformat(body["window_start"]) == since
        assert datetime.fromisoformat(body["window_end"]) == until

    def test_rejects_an_unparseable_window(self, client: TestClient) -> None:
        response = client.get("/v1/agents/agent-alpha/summary", params={"window": "7w"})

        assert response.status_code == 400

    def test_rejects_an_inverted_range(self, client: TestClient, now: datetime) -> None:
        response = client.get(
            "/v1/agents/agent-alpha/summary",
            params={
                "since": now.isoformat(),
                "until": (now - timedelta(hours=1)).isoformat(),
            },
        )

        assert response.status_code == 400


class TestUnknownAgent:
    def test_returns_a_zeroed_summary_rather_than_404(
        self, client: TestClient, seeded: dict[str, Any]
    ) -> None:
        """A dashboard can render "quiet" instead of special-casing a missing
        response."""
        body = get_summary(client, "agent-who")

        assert body["agent_id"] == "agent-who"
        assert body["total_alerts"] == 0
        assert body["total_events"] == 0
        assert body["max_severity"] is None
        assert body["top_rules"] == []
        assert body["severity_counts"] == {}
