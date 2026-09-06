"""Analyser configuration parsing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from analyser.config import AnalyserConfig, get_config, rule_config
from tests.conftest import DUMMY_DATABASE_URL, make_config


class TestAnalyserConfig:
    def test_parses_comma_separated_allowed_domains(self) -> None:
        """docker-compose passes ALLOWED_DOMAINS=a.com,b.com. Without the
        validator pydantic tries to parse that as JSON and fails at boot."""
        config = make_config(allowed_domains="a.com,b.com")

        assert config.allowed_domains == ["a.com", "b.com"]

    def test_accepts_a_real_list(self) -> None:
        """Passing a list directly, as tests do, still works."""
        assert make_config(allowed_domains=["a.com", "b.com"]).allowed_domains == [
            "a.com",
            "b.com",
        ]

    def test_trims_whitespace_around_domains(self) -> None:
        config = make_config(allowed_domains="a.com , b.com ,c.com  ")

        assert config.allowed_domains == ["a.com", "b.com", "c.com"]

    def test_drops_a_trailing_comma(self) -> None:
        assert make_config(allowed_domains="a.com,").allowed_domains == ["a.com"]

    def test_treats_an_empty_string_as_an_empty_list(self) -> None:
        assert make_config(allowed_domains="").allowed_domains == []

    def test_splits_secret_path_patterns_the_same_way(self) -> None:
        config = make_config(secret_path_patterns=".env, id_rsa")

        assert config.secret_path_patterns == [".env", "id_rsa"]

    def test_reads_values_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", DUMMY_DATABASE_URL)
        monkeypatch.setenv("ALLOWED_DOMAINS", "github.com,pypi.org")
        monkeypatch.setenv("BATCH_SIZE", "25")

        config = AnalyserConfig()

        assert config.allowed_domains == ["github.com", "pypi.org"]
        assert config.batch_size == 25

    def test_applies_defaults(self) -> None:
        config = make_config()

        assert config.batch_size == 200
        assert config.poller_enabled is True
        assert config.listen_enabled is True
        assert config.notify_channel == "events_ingested"
        assert config.allowed_domains == []
        assert ".env" in config.secret_path_patterns

    def test_requires_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing DATABASE_URL fails at construction, so the container dies
        at boot rather than on the first query."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(ValidationError):
            AnalyserConfig(_env_file=None)


class TestRuleConfig:
    def test_reports_the_settings_a_rule_reads(self) -> None:
        config = make_config(allowed_domains=["github.com"])

        assert rule_config("domain_allowlist", config) == {"allowed_domains": ["github.com"]}

    def test_returns_empty_for_a_rule_with_nothing_to_tune(self) -> None:
        assert rule_config("download_and_execute", make_config()) == {}

    def test_returns_empty_for_an_unknown_rule(self) -> None:
        assert rule_config("no_such_rule", make_config()) == {}

    def test_does_not_leak_the_database_url(self) -> None:
        """`GET /v1/rules` is unauthenticated, so this must stay a whitelist."""
        exposed = {
            key
            for rule in ("domain_allowlist", "secret_file_access", "download_and_execute")
            for key in rule_config(rule, make_config())
        }

        assert "database_url" not in exposed


class TestGetConfig:
    def test_parses_once_and_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FastAPI dependencies and the CLI must observe the same instance."""
        monkeypatch.setenv("DATABASE_URL", DUMMY_DATABASE_URL)
        get_config.cache_clear()

        assert get_config() is get_config()

        get_config.cache_clear()
