"""Analyser configuration parsing."""

from __future__ import annotations

import pytest


class TestAnalyserConfig:
    def test_parses_comma_separated_allowed_domains(self) -> None:
        """docker-compose passes ALLOWED_DOMAINS=a.com,b.com. Without the
        validator pydantic tries to parse that as JSON and fails at boot."""
        pytest.skip("TODO: implement")

    def test_accepts_a_real_list(self) -> None:
        """Passing a list directly, as tests do, still works."""
        pytest.skip("TODO: implement")

    def test_trims_whitespace_around_domains(self) -> None:
        pytest.skip("TODO: implement")

    def test_treats_an_empty_string_as_an_empty_list(self) -> None:
        pytest.skip("TODO: implement")

    def test_applies_defaults_for_thresholds(self) -> None:
        pytest.skip("TODO: implement")

    def test_requires_database_url(self) -> None:
        """A missing DATABASE_URL fails at construction, so the container dies
        at boot rather than on the first query."""
        pytest.skip("TODO: implement")


class TestPsycopgConninfo:
    def test_rewrites_postgres_scheme_to_postgresql(self) -> None:
        """docker-compose emits postgres://; libpq wants postgresql://."""
        pytest.skip("TODO: implement")

    def test_leaves_a_postgresql_url_unchanged(self) -> None:
        pytest.skip("TODO: implement")


class TestSeverityOrdering:
    def test_rank_orders_low_below_critical(self) -> None:
        pytest.skip("TODO: implement")

    def test_max_of_returns_the_highest(self) -> None:
        pytest.skip("TODO: implement")

    def test_max_of_returns_none_for_an_empty_list(self) -> None:
        pytest.skip("TODO: implement")
