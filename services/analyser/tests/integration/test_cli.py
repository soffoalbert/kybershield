"""The analyser CLI, exercised through typer's CliRunner.

Covers the "on-demand command" and "scheduled job" run modes the brief lists,
which the HTTP endpoints do not.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestRunOnceCommand:
    def test_analyses_pending_events(self) -> None:
        pytest.skip("TODO: implement")

    def test_prints_a_run_summary(self) -> None:
        pytest.skip("TODO: implement")

    def test_exits_zero_on_success(self) -> None:
        pytest.skip("TODO: implement")

    def test_exits_non_zero_when_a_rule_raised(self) -> None:
        """So a cron wrapper alerts on a broken detection instead of failing
        silently, which is the whole failure mode a scheduled job invites."""
        pytest.skip("TODO: implement")

    def test_drain_flag_processes_a_multi_batch_backlog(self) -> None:
        pytest.skip("TODO: implement")

    def test_batch_size_option_overrides_the_configured_default(self) -> None:
        pytest.skip("TODO: implement")

    def test_is_a_no_op_with_nothing_pending(self) -> None:
        pytest.skip("TODO: implement")


class TestBackfillCommand:
    def test_reanalyses_history(self) -> None:
        pytest.skip("TODO: implement")

    def test_since_option_limits_the_range(self) -> None:
        pytest.skip("TODO: implement")

    def test_repeat_run_writes_nothing(self) -> None:
        pytest.skip("TODO: implement")

    def test_leaves_the_live_cursor_untouched(self) -> None:
        pytest.skip("TODO: implement")


class TestListRulesCommand:
    def test_lists_every_rule_with_its_description(self) -> None:
        pytest.skip("TODO: implement")

    def test_shows_the_effective_thresholds(self) -> None:
        pytest.skip("TODO: implement")


class TestShowCursorCommand:
    def test_prints_the_current_watermark(self) -> None:
        pytest.skip("TODO: implement")

    def test_prints_the_pending_event_count(self) -> None:
        pytest.skip("TODO: implement")


class TestDatabaseUnavailable:
    def test_exits_non_zero_with_a_readable_message(self) -> None:
        pytest.skip("TODO: implement")
