"""Analyser configuration parsing."""

from __future__ import annotations

import pytest
from typing import Any, Optional

from services.analyser.config import (
    AnalyserConfig,
    get_psycopg_conninfo,
    Severity,
    max_of_severities,
)


class TestAnalyserConfig:
    def test_parses_comma_separated_allowed_domains(self) -> None:
        """docker-compose passes ALLOWED_DOMAINS=a.com,b.com. Without the
        validator pydantic tries to parse that as JSON and fails at boot."""
        c = AnalyserConfig(allowed_domains="a.com,b.com", database_url="postgresql://user:pass@host/db")
        assert c.allowed_domains == ["a.com", "b.com"]

    def test_accepts_a_real_list(self) -> None:
        """Passing a list directly, as tests do, still works."""
        c = AnalyserConfig(allowed_domains=["a.com", "b.com"], database_url="postgresql://user:pass@host/db")
        assert c.allowed_domains == ["a.com", "b.com"]

    def test_trims_whitespace_around_domains(self) -> None:
        c = AnalyserConfig(allowed_domains="a.com , b.com , c.com  ", database_url="postgresql://user:pass@host/db")
        assert c.allowed_domains == ["a.com", "b.com", "c.com"]

    def test_treats_an_empty_string_as_an_empty_list(self) -> None:
        c = AnalyserConfig(allowed_domains="", database_url="postgresql://user:pass@host/db")
        assert c.allowed_domains == []

    def test_applies_defaults_for_thresholds(self) -> None:
        c = AnalyserConfig(allowed_domains=[], database_url="postgresql://user:pass@host/db")
        # Defaults are implementation dependent; make sure they're set and are integers
        assert isinstance(c.threshold_low, int)
        assert isinstance(c.threshold_medium, int)
        assert isinstance(c.threshold_high, int)

    def test_requires_database_url(self) -> None:
        """A missing DATABASE_URL fails at construction, so the container dies
        at boot rather than on the first query."""
        with pytest.raises(TypeError):
            # database_url is required positional or keyword argument
            AnalyserConfig(allowed_domains=[])


class TestPsycopgConninfo:
    def test_rewrites_postgres_scheme_to_postgresql(self) -> None:
        """docker-compose emits postgres://; libpq wants postgresql://."""
        url = "postgres://user:pass@host:5432/db"
        conninfo = get_psycopg_conninfo(url)
        assert conninfo.startswith("postgresql://")
        assert conninfo[13:] == url[11:]  # everything after '//' should be identical

    def test_leaves_a_postgresql_url_unchanged(self) -> None:
        url = "postgresql://user:pass@host:5432/db"
        conninfo = get_psycopg_conninfo(url)
        assert conninfo == url


class TestSeverityOrdering:
    def test_rank_orders_low_below_critical(self) -> None:
        assert Severity.low.value < Severity.critical.value

    def test_max_of_returns_the_highest(self) -> None:
        result = max_of_severities([Severity.low, Severity.high, Severity.medium])
        assert result == Severity.high

    def test_max_of_returns_none_for_an_empty_list(self) -> None:
        result = max_of_severities([])
        assert result is None
