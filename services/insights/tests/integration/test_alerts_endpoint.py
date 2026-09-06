"""GET /v1/alerts against a seeded database.

Requires `docker compose up -d postgres`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pycommon import Database, Severity

from tests.conftest import seed_alert, seed_event

pytestmark = pytest.mark.integration


def get_alerts(client: TestClient, **params: Any) -> dict[str, Any]:
    """Call the endpoint, assert it answered 200, and return the body."""
    response = client.get("/v1/alerts", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ids_of(body: dict[str, Any]) -> list[str]:
    return [item["alert_id"] for item in body["items"]]


class TestDefaultWindow:
    def test_returns_alerts_from_the_last_24_hours(
        self, client: TestClient, seeded: dict[str, Any]
    ) -> None:
        """The brief's headline requirement."""
        body = get_alerts(client)

        assert ids_of(body) == seeded["recent"]
        assert body["total"] == 4

    def test_excludes_an_alert_older_than_24_hours(
        self, client: TestClient, seeded: dict[str, Any]
    ) -> None:
        """Seed one at now - 25h and assert it is absent. The complement of the
        test above, and the one that actually proves the filter runs."""
        body = get_alerts(client)

        assert seeded["alpha_old"] not in ids_of(body)

    def test_includes_an_alert_just_inside_the_boundary(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """now - 23h59m is included, pinning the boundary from the other
        side."""
        alert_id = seed_alert(db, created_at=now - timedelta(hours=23, minutes=59))

        assert ids_of(get_alerts(client)) == [alert_id]

    def test_orders_newest_first(self, client: TestClient, db: Database, now: datetime) -> None:
        oldest = seed_alert(db, created_at=now - timedelta(hours=3))
        newest = seed_alert(db, created_at=now - timedelta(minutes=5))
        middle = seed_alert(db, created_at=now - timedelta(hours=1))

        assert ids_of(get_alerts(client)) == [newest, middle, oldest]

    def test_ordering_is_stable_for_identical_timestamps(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """Ties break on alert_id, so pagination cannot show the same row twice
        or skip one between pages."""
        at = now - timedelta(hours=1)
        tied = [seed_alert(db, created_at=at) for _ in range(4)]

        assert ids_of(get_alerts(client)) == sorted(tied)


class TestFilters:
    def test_filters_by_agent_id(self, client: TestClient, seeded: dict[str, Any]) -> None:
        body = get_alerts(client, agent_id=seeded["beta"])

        assert ids_of(body) == seeded["beta_recent"]
        assert body["total"] == 1

    def test_filters_by_rule(self, client: TestClient, seeded: dict[str, Any]) -> None:
        body = get_alerts(client, rule="secret_file_access")

        assert {item["rule"] for item in body["items"]} == {"secret_file_access"}
        assert body["total"] == 2

    def test_filters_by_minimum_severity(self, client: TestClient, seeded: dict[str, Any]) -> None:
        """severity_min=high returns high and critical only, relying on the
        Postgres enum's ordering."""
        body = get_alerts(client, severity_min="high")

        assert {item["severity"] for item in body["items"]} == {"high", "critical"}
        assert body["total"] == 2

    def test_combines_filters_conjunctively(
        self, client: TestClient, seeded: dict[str, Any]
    ) -> None:
        """agent_id and rule together narrow rather than widen."""
        body = get_alerts(client, agent_id=seeded["alpha"], rule="secret_file_access")

        assert ids_of(body) == [seeded["alpha_recent"][1]]

    def test_rejects_an_invalid_severity(self, client: TestClient) -> None:
        """severity_min=urgent is a validation error, not a 500.

        400 with the shared `{error, issues}` envelope rather than FastAPI's
        default 422 `{detail}`, so all three services report a client mistake
        the same way.
        """
        response = client.get("/v1/alerts", params={"severity_min": "urgent"})

        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "validation_failed"
        assert [issue["path"] for issue in body["issues"]] == ["severity_min"]

    def test_accepts_an_explicit_since_and_until(
        self, client: TestClient, seeded: dict[str, Any], now: datetime
    ) -> None:
        body = get_alerts(
            client,
            since=(now - timedelta(hours=26)).isoformat(),
            until=(now - timedelta(hours=24)).isoformat(),
        )

        assert ids_of(body) == [seeded["alpha_old"]]

    def test_window_shorthand_widens_the_range(
        self, client: TestClient, seeded: dict[str, Any]
    ) -> None:
        body = get_alerts(client, window="7d")

        assert body["total"] == 5
        assert seeded["alpha_old"] in ids_of(body)

    def test_rejects_an_inverted_range(self, client: TestClient, now: datetime) -> None:
        response = client.get(
            "/v1/alerts",
            params={
                "since": now.isoformat(),
                "until": (now - timedelta(hours=1)).isoformat(),
            },
        )

        assert response.status_code == 400

    def test_rejects_an_unparseable_window(self, client: TestClient) -> None:
        response = client.get("/v1/alerts", params={"window": "7w"})

        assert response.status_code == 400


class TestPagination:
    @pytest.fixture
    def seven_alerts(self, db: Database, now: datetime) -> list[str]:
        """Seven alerts a minute apart, newest first."""
        return [seed_alert(db, created_at=now - timedelta(minutes=index)) for index in range(7)]

    def test_respects_limit(self, client: TestClient, seven_alerts: list[str]) -> None:
        body = get_alerts(client, limit=3)

        assert ids_of(body) == seven_alerts[:3]
        assert body["limit"] == 3

    def test_respects_offset(self, client: TestClient, seven_alerts: list[str]) -> None:
        body = get_alerts(client, limit=3, offset=3)

        assert ids_of(body) == seven_alerts[3:6]
        assert body["offset"] == 3

    def test_total_counts_all_matches_not_just_the_page(
        self, client: TestClient, seven_alerts: list[str]
    ) -> None:
        """What lets a dashboard size its paginator from a single request."""
        body = get_alerts(client, limit=2)

        assert len(body["items"]) == 2
        assert body["total"] == 7

    def test_total_reflects_the_active_filters(
        self, client: TestClient, db: Database, now: datetime, seven_alerts: list[str]
    ) -> None:
        seed_alert(db, agent_id="agent-beta", created_at=now)

        body = get_alerts(client, agent_id="agent-beta", limit=1)

        assert body["total"] == 1

    def test_clamps_limit_to_max_page_size(
        self, client: TestClient, seven_alerts: list[str]
    ) -> None:
        """An oversized limit is clamped rather than rejected: the caller gets
        data instead of an error."""
        body = get_alerts(client, limit=10_000)

        assert body["limit"] == client.app.state.config.max_page_size
        assert len(body["items"]) == 7

    def test_rejects_a_limit_below_one(self, client: TestClient) -> None:
        assert client.get("/v1/alerts", params={"limit": 0}).status_code == 400

    def test_offset_past_the_end_returns_an_empty_page(
        self, client: TestClient, seven_alerts: list[str]
    ) -> None:
        body = get_alerts(client, offset=100)

        assert body["items"] == []
        assert body["total"] == 7

    def test_pages_do_not_overlap_or_skip(
        self, client: TestClient, seven_alerts: list[str]
    ) -> None:
        """Walk every page and assert the union equals the full set exactly
        once."""
        walked: list[str] = []
        for offset in range(0, 9, 3):
            walked.extend(ids_of(get_alerts(client, limit=3, offset=offset)))

        assert walked == seven_alerts


class TestEmptyResults:
    def test_unknown_agent_returns_an_empty_page_not_404(
        self, client: TestClient, seeded: dict[str, Any]
    ) -> None:
        """A well-formed question whose answer is "nothing" is a 200. A 404
        would conflate it with a malformed request."""
        body = get_alerts(client, agent_id="agent-who")

        assert body["items"] == []
        assert body["total"] == 0

    def test_empty_database_returns_an_empty_page(self, client: TestClient) -> None:
        body = get_alerts(client)

        assert body == {
            "items": [],
            "total": 0,
            "limit": 50,
            "offset": 0,
            "has_more": False,
        }


class TestResponseShape:
    def test_items_carry_every_documented_field(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        event_id = seed_event(db, agent_id="agent-alpha", occurred_at=now)
        alert_id = seed_alert(
            db,
            event_id=event_id,
            agent_id="agent-alpha",
            rule="secret_file_access",
            severity=Severity.HIGH,
            created_at=now - timedelta(minutes=1),
            summary="read /app/.env",
        )

        item = get_alerts(client)["items"][0]

        assert set(item) == {
            "alert_id",
            "agent_id",
            "event_id",
            "timestamp",
            "rule",
            "severity",
            "summary",
        }
        assert item["alert_id"] == alert_id
        assert item["agent_id"] == "agent-alpha"
        assert item["rule"] == "secret_file_access"
        assert item["summary"] == "read /app/.env"
        assert item["event_id"] == event_id

    def test_timestamps_serialise_as_iso_8601_utc(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        created_at = now - timedelta(minutes=1)
        seed_alert(db, created_at=created_at)

        timestamp = get_alerts(client)["items"][0]["timestamp"]

        parsed = datetime.fromisoformat(timestamp)
        assert parsed.utcoffset() == timedelta(0)
        assert parsed == created_at

    def test_severity_serialises_as_a_lowercase_string(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        seed_alert(db, severity=Severity.CRITICAL, created_at=now)

        assert get_alerts(client)["items"][0]["severity"] == "critical"


class TestHealthz:
    def test_reports_ok_when_the_database_responds(self, client: TestClient) -> None:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": True}

    def test_answers_503_when_the_database_is_down(self, client: TestClient) -> None:
        """A structured 503, not a 500 with a stack trace."""
        client.app.state.db.close()

        response = client.get("/healthz")

        assert response.status_code == 503
        assert response.json() == {"status": "degraded", "database": False}
