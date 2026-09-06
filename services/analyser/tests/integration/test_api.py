"""Analyser HTTP endpoints.

Driven with the poller disabled, so a pass happens only when a test asks for
one and assertions are not racing a background loop.
"""

from __future__ import annotations

import pytest
import requests
from time import sleep

pytestmark = pytest.mark.integration

BASE_URL = "http://localhost:8080"  # Adjust if necessary


class TestAnalyzeRun:
    def test_returns_a_run_report(self) -> None:
        """POST /v1/analyze/run answers 200 with the counts and cursor movement."""
        resp = requests.post(f"{BASE_URL}/v1/analyze/run")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("written", "counts", "cursor"):
            assert key in data

    def test_writes_alerts_for_pending_events(self) -> None:
        # Setup: Add an event that should trigger an alert
        event = {"event_type": "pending_alert", "details": {"foo": "bar"}}
        requests.post(f"{BASE_URL}/v1/events", json=[event])
        resp = requests.post(f"{BASE_URL}/v1/analyze/run")
        data = resp.json()
        assert resp.status_code == 200
        # At least one written
        assert data["written"] > 0
        # The event is now handled, subsequent run should not write it again
        resp2 = requests.post(f"{BASE_URL}/v1/analyze/run")
        assert resp2.json()["written"] == 0

    def test_reports_zero_written_on_a_second_call(self) -> None:
        # First call: should process all available events
        requests.post(f"{BASE_URL}/v1/analyze/run")
        # Second call: nothing new, so written should be 0
        resp = requests.post(f"{BASE_URL}/v1/analyze/run")
        assert resp.status_code == 200
        assert resp.json()["written"] == 0

    def test_answers_503_when_the_database_is_unreachable(self) -> None:
        # Simulate database down (assuming test DB can be stopped/refused)
        # This requires the test DB to be controllable from the test context.
        # For CI: skip or mock DB failures.
        try:
            requests.post(f"{BASE_URL}/v1/analyze/run", timeout=3)
        except requests.exceptions.ConnectionError:
            pytest.skip("Database is not running; unable to test 503 scenario")
        else:
            resp = requests.post(f"{BASE_URL}/v1/analyze/run", headers={"X-Simulate-DB-Down": "1"})
            assert resp.status_code == 503


class TestAnalyzeBackfill:
    def test_accepts_an_empty_body(self) -> None:
        """No `since` means all history."""
        resp = requests.post(f"{BASE_URL}/v1/analyze/backfill", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "written" in data

    def test_accepts_a_since_timestamp(self) -> None:
        payload = {"since": "2024-01-01T00:00:00Z"}
        resp = requests.post(f"{BASE_URL}/v1/analyze/backfill", json=payload)
        assert resp.status_code == 200
        assert "written" in resp.json()

    def test_rejects_a_malformed_since(self) -> None:
        payload = {"since": "not-a-timestamp"}
        resp = requests.post(f"{BASE_URL}/v1/analyze/backfill", json=payload)
        assert resp.status_code == 400 or (
            resp.status_code == 422  # Depending on API style
        )


class TestListRules:
    def test_lists_every_registered_rule(self) -> None:
        resp = requests.get(f"{BASE_URL}/v1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert all("name" in rule for rule in data)

    def test_includes_the_effective_configuration(self) -> None:
        """A reviewer can read the live thresholds without inspecting the container's environment."""
        resp = requests.get(f"{BASE_URL}/v1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert all("config" in rule for rule in data)


class TestHealthz:
    def test_reports_ok_when_the_database_responds(self) -> None:
        resp = requests.get(f"{BASE_URL}/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"

    def test_reports_poller_state(self) -> None:
        resp = requests.get(f"{BASE_URL}/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert "poller" in data

    def test_answers_503_when_the_database_is_down(self) -> None:
        # This requires ability to simulate DB failure as above
        try:
            requests.get(f"{BASE_URL}/healthz", timeout=3)
        except requests.exceptions.ConnectionError:
            pytest.skip("Database is not running; unable to test 503 scenario")
        else:
            resp = requests.get(f"{BASE_URL}/healthz", headers={"X-Simulate-DB-Down": "1"})
            assert resp.status_code == 503


class TestPoller:
    def test_runs_a_pass_on_its_interval(self) -> None:
        # If we can set the poller to a short interval
        sleep(2)  # Wait for a poller interval
        # Check state endpoint
        resp = requests.get(f"{BASE_URL}/v1/poller/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "last_pass" in data

    def test_keeps_running_after_a_failed_pass(self) -> None:
        # Simulate a bad event that will cause a poller pass to fail,
        # then check that poller recovers
        bad_event = {"event_type": "error_event", "details": {"cause": "fail"}}
        requests.post(f"{BASE_URL}/v1/events", json=[bad_event])
        sleep(2)
        resp = requests.get(f"{BASE_URL}/v1/poller/state")
        data = resp.json()
        assert data["consecutive_failures"] >= 1 or data.get("last_failure") is not None
        # Ensure it keeps running after failure
        sleep(2)
        resp2 = requests.get(f"{BASE_URL}/v1/poller/state")
        assert resp2.status_code == 200

    def test_counts_consecutive_failures_in_its_state(self) -> None:
        # Cause several poller failures
        for _ in range(2):
            bad_event = {"event_type": "fail_event", "details": {"cause": "fail"}}
            requests.post(f"{BASE_URL}/v1/events", json=[bad_event])
            sleep(1)
        resp = requests.get(f"{BASE_URL}/v1/poller/state")
        data = resp.json()
        assert data["consecutive_failures"] >= 2

    def test_stops_cleanly_on_shutdown(self) -> None:
        # This requires stopping the application; may not be feasible in integration context
        # Instead, check that the shutdown endpoint triggers a clean stop
        resp = requests.post(f"{BASE_URL}/v1/shutdown")
        assert resp.status_code == 200 or resp.status_code == 202

    def test_does_not_block_http_endpoints_during_a_pass(self) -> None:
        """The reason the synchronous engine runs in a thread executor: a slow
        pass must not stall /healthz."""
        # Insert a long operation
        resp = requests.post(f"{BASE_URL}/v1/events", json=[{"event_type": "slow_pass", "details": {"sleep": 3}}])
        # Immediately call /healthz, it should answer quickly
        resp2 = requests.get(f"{BASE_URL}/healthz", timeout=1)
        assert resp2.status_code == 200
