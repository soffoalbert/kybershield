"""Time window parsing and resolution.

Pure functions shared by the HTTP API and the CLI, so they are worth pinning
precisely: an off-by-one here silently changes what every endpoint returns.
"""

from __future__ import annotations

import pytest


class TestParseWindow:
    def test_parses_minutes(self) -> None:
        """'30m' is 30 minutes."""
        pytest.skip("TODO: implement")

    def test_parses_hours(self) -> None:
        pytest.skip("TODO: implement")

    def test_parses_days(self) -> None:
        pytest.skip("TODO: implement")

    def test_is_case_insensitive(self) -> None:
        """'24H' parses."""
        pytest.skip("TODO: implement")

    def test_rejects_an_unknown_suffix(self) -> None:
        """'7w' raises ValueError rather than guessing."""
        pytest.skip("TODO: implement")

    def test_rejects_a_missing_suffix(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_a_non_integer_quantity(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_zero(self) -> None:
        """A zero-length window would return nothing, which is never what the
        caller meant."""
        pytest.skip("TODO: implement")

    def test_rejects_a_negative_duration(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_an_empty_string(self) -> None:
        pytest.skip("TODO: implement")


class TestResolveWindow:
    def test_uses_explicit_since_and_until_verbatim(self) -> None:
        pytest.skip("TODO: implement")

    def test_window_takes_precedence_over_the_default(self) -> None:
        pytest.skip("TODO: implement")

    def test_since_alone_runs_to_now(self) -> None:
        pytest.skip("TODO: implement")

    def test_falls_back_to_the_default_hours(self) -> None:
        """The brief's "last 24 hours", applied when the caller says
        nothing."""
        pytest.skip("TODO: implement")

    def test_treats_a_naive_datetime_as_utc(self) -> None:
        """A teammate typing 2026-08-25T10:00:00 on the CLI plainly means UTC;
        rejecting it would be pedantic, and guessing local time would be
        wrong."""
        pytest.skip("TODO: implement")

    def test_returns_timezone_aware_bounds(self) -> None:
        """Comparing a naive bound against a timestamptz column raises in
        psycopg, so both bounds must be aware."""
        pytest.skip("TODO: implement")

    def test_rejects_an_inverted_range(self) -> None:
        """since after until raises rather than silently returning nothing."""
        pytest.skip("TODO: implement")

    def test_propagates_an_unparseable_window(self) -> None:
        pytest.skip("TODO: implement")

    def test_uses_the_injected_now(self) -> None:
        """Injectable time is what keeps these deterministic without freezing
        the clock globally."""
        pytest.skip("TODO: implement")
