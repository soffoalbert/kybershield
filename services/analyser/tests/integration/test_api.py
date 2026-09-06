"""Analyser HTTP endpoints.

Driven with the poller disabled, so a pass happens only when a test asks for
one and assertions are not racing a background loop.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from pycommon import Database

from tests.integration.conftest import read_alerts, seed_event, seed_secret_read

pytestmark = pytest.mark.integration


class TestAnalyzeRun:
    def test_returns_a_run_report(self, client: TestClient) -> None:
        response = client.post("/v1/analyze/run")

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "events_examined",
            "alerts_generated",
            "alerts_written",
            "cursor_before",
            "cursor_after",
            "duration_ms",
            "rule_failures",
        }
        assert body["events_examined"] == 0
        assert body["cursor_before"] == body["cursor_after"] == 0
        assert body["rule_failures"] == []

    def test_writes_alerts_for_pending_events(self, db: Database, client: TestClient) -> None:
        seed_secret_read(db, event_id="evt-1")

        body = client.post("/v1/analyze/run").json()

        assert body["events_examined"] == 1
        assert body["alerts_written"] == 1
        assert body["cursor_after"] > body["cursor_before"]
        assert [alert.rule for alert in read_alerts(db)] == ["secret_file_access"]

    def test_reports_zero_written_on_a_second_call(self, db: Database, client: TestClient) -> None:
        seed_secret_read(db)
        client.post("/v1/analyze/run")

        body = client.post("/v1/analyze/run").json()

        assert body["events_examined"] == 0
        assert body["alerts_written"] == 0

    def test_drain_clears_a_backlog_larger_than_one_batch(
        self, db: Database, client: TestClient
    ) -> None:
        """What a reviewer wants right after seeding demo data."""
        for seq in range(1, 4):
            seed_secret_read(db, event_id=f"evt-{seq}")

        body = client.post("/v1/analyze/run", params={"drain": True}).json()

        assert body["events_examined"] == 3
        assert body["alerts_written"] == 3

    def test_runs_the_rules_the_environment_configured(
        self, db: Database, client: TestClient
    ) -> None:
        """ALLOWED_DOMAINS reaches the rule through the app's own config."""
        seed_event(db, type_="http_request", payload={"url": "https://evil.example.com"})

        body = client.post("/v1/analyze/run").json()

        assert body["alerts_written"] == 1
        assert [alert.rule for alert in read_alerts(db)] == ["domain_allowlist"]
        assert body["rule_failures"] == []


class TestAnalyzeBackfill:
    def test_accepts_an_empty_body(self, db: Database, client: TestClient) -> None:
        """No `since` means all history."""
        seed_secret_read(db)

        response = client.post("/v1/analyze/backfill", json={})

        assert response.status_code == 200
        assert response.json()["alerts_written"] == 1

    def test_accepts_a_since_timestamp(self, db: Database, client: TestClient) -> None:
        seed_secret_read(db)

        response = client.post("/v1/analyze/backfill", json={"since": "2999-01-01T00:00:00Z"})

        assert response.status_code == 200
        assert response.json()["events_examined"] == 0

    def test_leaves_the_cursor_where_it_was(self, db: Database, client: TestClient) -> None:
        seed_secret_read(db)

        body = client.post("/v1/analyze/backfill", json={}).json()

        assert body["cursor_before"] == body["cursor_after"] == 0

    def test_rejects_a_malformed_since(self, client: TestClient) -> None:
        """400 with the shared `{error, issues}` envelope, not FastAPI's
        default 422 `{detail}`: a bad body is the same class of client mistake
        the ingestion service already answers 400 for, and one error shape
        across all three services is one less thing for a client to branch on.
        """
        response = client.post("/v1/analyze/backfill", json={"since": "not-a-timestamp"})

        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "validation_failed"
        assert [issue["path"] for issue in body["issues"]] == ["since"]


class TestListRules:
    def test_lists_every_registered_rule(self, client: TestClient) -> None:
        response = client.get("/v1/rules")

        assert response.status_code == 200
        assert [rule["id"] for rule in response.json()] == [
            "domain_allowlist",
            "download_and_execute",
            "secret_file_access",
        ]

    def test_includes_the_effective_configuration(self, client: TestClient) -> None:
        """A reviewer can read the live thresholds without inspecting the
        container's environment."""
        rules = {rule["id"]: rule["config"] for rule in client.get("/v1/rules").json()}

        assert rules["domain_allowlist"] == {"allowed_domains": ["github.com"]}
        assert rules["download_and_execute"] == {}

    def test_does_not_expose_the_database_url(self, client: TestClient) -> None:
        """The endpoint is unauthenticated, so the whitelist has to hold."""
        assert "database_url" not in client.get("/v1/rules").text


class TestHealthz:
    def test_reports_ok_when_the_database_responds(self, client: TestClient) -> None:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["database"] is True

    def test_reports_poller_state(self, client: TestClient) -> None:
        """The poller is off in tests, and health says so rather than lying."""
        body = client.get("/healthz").json()

        assert body["poller_running"] is False
        assert body["last_run_at"] is None
        assert body["consecutive_failures"] == 0
        assert body["listener_connected"] is False
        assert body["notify_wakeups"] == 0

    def test_reports_a_running_poller_and_listener_when_enabled(
        self, polling_client: TestClient
    ) -> None:
        """The wiring production uses: lifespan starts both on boot.

        Every other test here runs with them off, so without this the default
        configuration would go unexercised.
        """
        assert polling_client.get("/healthz").json()["poller_running"] is True

        # The listener connects in a background task, so `connected` flips a
        # round trip after startup rather than during it. Health reporting that
        # honestly is the point of the field; the test just has to wait for it.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if polling_client.get("/healthz").json()["listener_connected"]:
                return
            time.sleep(0.05)

        raise AssertionError("listener never reported itself connected")

    def test_answers_503_when_the_database_is_down(self, client: TestClient) -> None:
        """A structured 503, not a 500 with a stack trace."""
        client.app.state.db.close()

        response = client.get("/healthz")

        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["database"] is False
