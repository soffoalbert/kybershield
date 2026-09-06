"""SecretFileAccessRule."""

from __future__ import annotations

from typing import Any

from pycommon import Event, Severity

from analyser.rules.secret_file_access import SecretFileAccessRule, matches_secret_path
from tests.conftest import make_config, make_event


def read_event(path: Any, **kwargs: Any) -> Event:
    """A `file_read` event for `path`, the only shape this rule looks at."""
    return make_event(type_="file_read", payload={"path": path}, **kwargs)


def alerts_for(event: Event, patterns: list[str] | None = None) -> list:
    """Run the rule over `event`, defaulting to the configured patterns."""
    overrides = {"secret_path_patterns": patterns} if patterns is not None else {}
    return SecretFileAccessRule().evaluate(event, make_config(**overrides))


class TestSecretFileAccessRule:
    def test_fires_on_dotenv_read(self) -> None:
        alerts = alerts_for(read_event("/app/.env"))

        assert len(alerts) == 1
        assert alerts[0].rule == "secret_file_access"
        assert alerts[0].severity == Severity.HIGH

    def test_fires_on_aws_credentials(self) -> None:
        alerts = alerts_for(read_event("/home/agent/.aws/credentials"))

        assert alerts[0].details["matched_patterns"] == [".aws/credentials"]

    def test_fires_on_ssh_private_key(self) -> None:
        alerts = alerts_for(read_event("/root/.ssh/id_rsa"))

        assert "id_rsa" in alerts[0].details["matched_patterns"]

    def test_fires_on_a_suffixed_secret_file(self) -> None:
        """Substring matching is the point: `.env.production` still counts."""
        assert len(alerts_for(read_event("/srv/app/.env.production"))) == 1

    def test_fires_on_a_backup_copy(self) -> None:
        assert len(alerts_for(read_event("/backup/id_rsa.bak"))) == 1

    def test_match_is_case_insensitive(self) -> None:
        assert len(alerts_for(read_event("/APP/.ENV"))) == 1

    def test_ignores_an_ordinary_file(self) -> None:
        assert alerts_for(read_event("/etc/hosts")) == []

    def test_ignores_non_file_read_event(self) -> None:
        event = make_event(type_="shell_command", payload={"path": "/app/.env"})

        assert alerts_for(event) == []

    def test_ignores_missing_path(self) -> None:
        assert alerts_for(make_event(type_="file_read", payload={})) == []

    def test_ignores_non_string_path(self) -> None:
        assert alerts_for(read_event(1234)) == []
        assert alerts_for(read_event(["/app/.env"])) == []

    def test_emits_one_alert_when_several_patterns_match(self) -> None:
        alerts = alerts_for(read_event("/root/.ssh/id_rsa"))

        assert len(alerts) == 1
        assert set(alerts[0].details["matched_patterns"]) == {".ssh/", "id_rsa"}

    def test_alert_carries_the_path_and_the_event_identity(self) -> None:
        alerts = alerts_for(read_event("/app/.env", event_id="evt-9", agent_id="agent-beta"))

        alert = alerts[0]
        assert alert.event_id == "evt-9"
        assert alert.agent_id == "agent-beta"
        assert alert.details["path"] == "/app/.env"
        assert "/app/.env" in alert.summary

    def test_respects_configured_patterns(self) -> None:
        patterns = ["customsecret"]

        assert len(alerts_for(read_event("/opt/customsecret.txt"), patterns)) == 1
        assert alerts_for(read_event("/app/.env"), patterns) == []


class TestMatchesSecretPath:
    def test_returns_every_matching_pattern(self) -> None:
        matched = matches_secret_path("/opt/files/.env.production", [".env", "id_rsa", ".pem"])

        assert matched == [".env"]

    def test_returns_empty_for_no_match(self) -> None:
        assert matches_secret_path("/foo/bar/baz.txt", [".env", "id_rsa"]) == []

    def test_handles_an_empty_pattern_list(self) -> None:
        assert matches_secret_path("/app/.env", []) == []

    def test_lowercases_operator_supplied_patterns(self) -> None:
        """A pattern typed as `.AWS/credentials` must behave like the default."""
        assert matches_secret_path("/home/a/.aws/credentials", [".AWS/credentials"]) == [
            ".AWS/credentials"
        ]
