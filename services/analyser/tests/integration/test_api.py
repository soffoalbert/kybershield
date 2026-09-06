"""Analyser HTTP endpoints.

Driven with the poller disabled, so a pass happens only when a test asks for
one and assertions are not racing a background loop.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestAnalyzeRun:
    def test_returns_a_run_report(self) -> None:
        """POST /v1/analyze/run answers 200 with the counts and cursor
        movement."""
        pytest.skip("TODO: implement")

    def test_writes_alerts_for_pending_events(self) -> None:
        pytest.skip("TODO: implement")

    def test_reports_zero_written_on_a_second_call(self) -> None:
        pytest.skip("TODO: implement")

    def test_answers_503_when_the_database_is_unreachable(self) -> None:
        pytest.skip("TODO: implement")


class TestAnalyzeBackfill:
    def test_accepts_an_empty_body(self) -> None:
        """No `since` means all history."""
        pytest.skip("TODO: implement")

    def test_accepts_a_since_timestamp(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_a_malformed_since(self) -> None:
        pytest.skip("TODO: implement")


class TestListRules:
    def test_lists_every_registered_rule(self) -> None:
        pytest.skip("TODO: implement")

    def test_includes_the_effective_configuration(self) -> None:
        """A reviewer can read the live thresholds without inspecting the
        container's environment."""
        pytest.skip("TODO: implement")


class TestHealthz:
    def test_reports_ok_when_the_database_responds(self) -> None:
        pytest.skip("TODO: implement")

    def test_reports_poller_state(self) -> None:
        pytest.skip("TODO: implement")

    def test_answers_503_when_the_database_is_down(self) -> None:
        pytest.skip("TODO: implement")


class TestPoller:
    def test_runs_a_pass_on_its_interval(self) -> None:
        pytest.skip("TODO: implement")

    def test_keeps_running_after_a_failed_pass(self) -> None:
        """A crashed poller would leave the service up and apparently healthy
        while silently analysing nothing, which is the worst failure mode
        available to it."""
        pytest.skip("TODO: implement")

    def test_counts_consecutive_failures_in_its_state(self) -> None:
        pytest.skip("TODO: implement")

    def test_stops_cleanly_on_shutdown(self) -> None:
        pytest.skip("TODO: implement")

    def test_does_not_block_http_endpoints_during_a_pass(self) -> None:
        """The reason the synchronous engine runs in a thread executor: a slow
        pass must not stall /healthz."""
        pytest.skip("TODO: implement")
