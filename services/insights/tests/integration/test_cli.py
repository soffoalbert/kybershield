"""The insights CLI, exercised through typer's CliRunner.

Worth covering because the CLI is a second consumer of the same repository, and
`--json` is asserted to match the HTTP contract so the two cannot drift.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestAlertsCommand:
    def test_prints_a_table_by_default(self) -> None:
        pytest.skip("TODO: implement")

    def test_json_output_matches_the_http_response_shape(self) -> None:
        """Guards against the CLI and the API drifting into two different
        contracts for the same data."""
        pytest.skip("TODO: implement")

    def test_applies_the_agent_filter(self) -> None:
        pytest.skip("TODO: implement")

    def test_applies_the_rule_filter(self) -> None:
        pytest.skip("TODO: implement")

    def test_applies_the_window(self) -> None:
        pytest.skip("TODO: implement")

    def test_exits_zero_with_no_results(self) -> None:
        """No alerts is good news, not an error condition."""
        pytest.skip("TODO: implement")

    def test_exits_non_zero_on_an_invalid_window(self) -> None:
        pytest.skip("TODO: implement")


class TestSummaryCommand:
    def test_prints_totals_and_top_rules(self) -> None:
        pytest.skip("TODO: implement")

    def test_json_output_matches_the_http_response_shape(self) -> None:
        pytest.skip("TODO: implement")

    def test_handles_an_unknown_agent(self) -> None:
        pytest.skip("TODO: implement")


class TestTimelineCommand:
    def test_interleaves_events_and_alerts(self) -> None:
        pytest.skip("TODO: implement")

    def test_json_output_matches_the_http_response_shape(self) -> None:
        pytest.skip("TODO: implement")

    def test_respects_the_limit(self) -> None:
        pytest.skip("TODO: implement")


class TestAgentsCommand:
    def test_lists_known_agents_with_first_and_last_seen(self) -> None:
        pytest.skip("TODO: implement")

    def test_prints_a_clear_message_when_none_exist(self) -> None:
        pytest.skip("TODO: implement")


class TestDatabaseUnavailable:
    def test_exits_non_zero_with_a_readable_message(self) -> None:
        """Not a stack trace: the CLI is the demo surface and a traceback there
        reads as a broken tool."""
        pytest.skip("TODO: implement")
