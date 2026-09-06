"""The command-line entrypoint against real PostgreSQL.

`python -m analyser run-once` is one of the three ways the brief allows the
analyser to run, so it gets the same treatment as the HTTP surface. Every
command opens its own pool, which is why these are integration tests.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pycommon import Database
from typer.testing import CliRunner

from analyser import cli
from analyser.config import get_config
from tests.conftest import FIXED_NOW, BrokenRule, StubRule
from tests.integration.conftest import read_alerts, read_cursor, seed_secret_read, set_cursor

pytestmark = pytest.mark.integration


@pytest.fixture
def run(db: Database, db_url: str, monkeypatch: pytest.MonkeyPatch):
    """Invoke a CLI command against the test database.

    Depends on `db` so the tables are truncated first, and clears the config
    cache because the CLI reads `DATABASE_URL` through the same `lru_cache` the
    API does.
    """
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ALLOWED_DOMAINS", "github.com")
    get_config.cache_clear()
    runner = CliRunner()

    def _run(*args: str):
        return runner.invoke(cli.app, list(args))

    yield _run

    get_config.cache_clear()


class TestRunOnce:
    def test_analyses_pending_events_and_prints_a_report(self, run, db: Database) -> None:
        seed_secret_read(db, event_id="evt-1")

        result = run("run-once")

        assert result.exit_code == 0
        report = json.loads(result.stdout)
        assert report["events_examined"] == 1
        assert report["alerts_written"] == 1
        assert [alert.rule for alert in read_alerts(db)] == ["secret_file_access"]

    def test_prints_json_so_the_output_pipes_into_jq(self, run) -> None:
        """The reason it is not the dataclass repr: a cron wrapper parses it."""
        report = json.loads(run("run-once").stdout)

        assert report["events_examined"] == 0
        assert report["rule_failures"] == []

    def test_advances_the_persisted_cursor(self, run, db: Database) -> None:
        last_seq = seed_secret_read(db, event_id="evt-1")

        run("run-once")

        assert read_cursor(db) == last_seq

    def test_batch_size_limits_one_pass(self, run, db: Database) -> None:
        for index in range(4):
            seed_secret_read(db, event_id=f"evt-{index}")

        report = json.loads(run("run-once", "--batch-size", "2").stdout)

        assert report["events_examined"] == 2

    def test_drain_clears_the_whole_backlog(self, run, db: Database) -> None:
        for index in range(4):
            seed_secret_read(db, event_id=f"evt-{index}")

        report = json.loads(run("run-once", "--batch-size", "2", "--drain").stdout)

        # `--drain` ignores --batch-size, which run_until_caught_up does not
        # take; what matters is that nothing is left behind.
        assert report["events_examined"] == 4
        assert len(read_alerts(db)) == 4

    def test_exits_non_zero_when_a_rule_raised(
        self, run, db: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """So a cron wrapper alerts on a broken detection instead of failing
        silently."""
        monkeypatch.setattr(cli, "default_rules", lambda: [BrokenRule(), StubRule("healthy")])
        seed_secret_read(db, event_id="evt-1")

        result = run("run-once")

        assert result.exit_code == 1
        # The pass still committed what the healthy rules found.
        assert [alert.rule for alert in read_alerts(db)] == ["healthy"]

    def test_exits_zero_on_an_empty_database(self, run) -> None:
        assert run("run-once").exit_code == 0


class TestBackfill:
    def test_reanalyses_history(self, run, db: Database) -> None:
        seed_secret_read(db, event_id="evt-1")
        seed_secret_read(db, event_id="evt-2")

        report = json.loads(run("backfill").stdout)

        assert report["alerts_written"] == 2

    def test_leaves_the_cursor_untouched(self, run, db: Database) -> None:
        seed_secret_read(db, event_id="evt-1")
        set_cursor(db, 7)

        run("backfill")

        assert read_cursor(db) == 7

    def test_is_safe_to_repeat(self, run, db: Database) -> None:
        seed_secret_read(db, event_id="evt-1")
        run("backfill")

        report = json.loads(run("backfill").stdout)

        assert report["alerts_generated"] == 1
        assert report["alerts_written"] == 0

    def test_since_limits_the_range(self, run, db: Database) -> None:
        seed_secret_read(db, event_id="old", occurred_at=FIXED_NOW - timedelta(days=2))
        seed_secret_read(db, event_id="recent", occurred_at=FIXED_NOW)

        # Typer's datetime option accepts no UTC offset, so the bound goes in
        # naive and Postgres reads it in the session timezone. The two events
        # are two days apart, so any plausible skew still separates them.
        since = (FIXED_NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

        report = json.loads(run("backfill", "--since", since).stdout)

        assert report["events_examined"] == 1
        assert [alert.event_id for alert in read_alerts(db)] == ["recent"]


class TestListRules:
    def test_prints_every_rule_with_its_effective_config(self, run) -> None:
        rules = json.loads(run("list-rules").stdout)

        assert [rule["id"] for rule in rules] == [
            "domain_allowlist",
            "download_and_execute",
            "secret_file_access",
        ]
        assert rules[0]["config"] == {"allowed_domains": ["github.com"]}
        assert all(rule["description"] for rule in rules)

    def test_does_not_print_the_database_url(self, run) -> None:
        assert "database_url" not in run("list-rules").stdout


class TestShowCursor:
    def test_prints_the_watermark(self, run, db: Database) -> None:
        set_cursor(db, 42)

        assert run("show-cursor").stdout.strip() == "42"

    def test_prints_zero_before_the_first_run(self, run) -> None:
        assert run("show-cursor").stdout.strip() == "0"


class TestUsage:
    def test_bare_invocation_prints_help(self, run) -> None:
        """`no_args_is_help`, so a mistyped cron entry explains itself."""
        result = run()

        assert "run-once" in result.stdout
        assert "backfill" in result.stdout

    def test_an_unknown_command_fails(self, run) -> None:
        assert run("nonsense").exit_code != 0
