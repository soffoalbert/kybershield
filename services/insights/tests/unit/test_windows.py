"""Time window parsing and resolution.

Pure functions behind every endpoint's time range, so they are worth pinning
precisely: an off-by-one here silently changes what every endpoint returns.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from insights.windows import parse_window, resolve_window

#: Injected as `now` throughout, so every expectation can be written out in
#: full rather than computed from the clock.
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


class TestParseWindow:
    def test_parses_minutes(self) -> None:
        """'30m' is 30 minutes."""
        assert parse_window("30m") == timedelta(minutes=30)

    def test_parses_hours(self) -> None:
        assert parse_window("24h") == timedelta(hours=24)

    def test_parses_days(self) -> None:
        assert parse_window("7d") == timedelta(days=7)

    def test_is_case_insensitive(self) -> None:
        """'24H' parses."""
        assert parse_window("24H") == timedelta(hours=24)

    def test_rejects_an_unknown_suffix(self) -> None:
        """'7w' raises ValueError rather than guessing."""
        with pytest.raises(ValueError):
            parse_window("7w")

    def test_rejects_a_missing_suffix(self) -> None:
        with pytest.raises(ValueError):
            parse_window("24")

    def test_rejects_a_non_integer_quantity(self) -> None:
        with pytest.raises(ValueError):
            parse_window("1.5h")

    def test_rejects_zero(self) -> None:
        """A zero-length window would return nothing, which is never what the
        caller meant."""
        with pytest.raises(ValueError):
            parse_window("0h")

    def test_rejects_a_negative_duration(self) -> None:
        with pytest.raises(ValueError):
            parse_window("-1h")

    def test_rejects_an_empty_string(self) -> None:
        with pytest.raises(ValueError):
            parse_window("")


class TestResolveWindow:
    def test_uses_explicit_since_and_until_verbatim(self) -> None:
        since = datetime(2026, 8, 1, tzinfo=UTC)
        until = datetime(2026, 8, 2, tzinfo=UTC)

        assert resolve_window(since, until, None, 24, now=NOW) == (since, until)

    def test_window_takes_precedence_over_the_default(self) -> None:
        start, end = resolve_window(None, None, "7d", 24, now=NOW)

        assert (start, end) == (NOW - timedelta(days=7), NOW)

    def test_since_alone_runs_to_now(self) -> None:
        since = NOW - timedelta(hours=3)

        assert resolve_window(since, None, None, 24, now=NOW) == (since, NOW)

    def test_falls_back_to_the_default_hours(self) -> None:
        """The brief's "last 24 hours", applied when the caller says
        nothing."""
        start, end = resolve_window(None, None, None, 24, now=NOW)

        assert (start, end) == (NOW - timedelta(hours=24), NOW)

    def test_the_default_hours_is_configurable(self) -> None:
        start, _ = resolve_window(None, None, None, 6, now=NOW)

        assert start == NOW - timedelta(hours=6)

    def test_treats_a_naive_datetime_as_utc(self) -> None:
        """A teammate passing 2026-08-25T10:00:00 plainly means UTC;
        rejecting it would be pedantic, and guessing local time would be
        wrong."""
        start, _ = resolve_window(datetime(2026, 8, 25, 10, 0), None, None, 24, now=NOW)

        assert start == datetime(2026, 8, 25, 10, 0, tzinfo=UTC)

    def test_normalises_a_non_utc_offset(self) -> None:
        noon_in_paris = datetime(2026, 8, 25, 12, 0, tzinfo=timezone(timedelta(hours=2)))

        start, _ = resolve_window(noon_in_paris, None, None, 24, now=NOW)

        assert start == datetime(2026, 8, 25, 10, 0, tzinfo=UTC)

    def test_returns_timezone_aware_bounds(self) -> None:
        """Comparing a naive bound against a timestamptz column raises in
        psycopg, so both bounds must be aware."""
        start, end = resolve_window(None, None, None, 24, now=datetime(2026, 8, 25, 12, 0))

        assert start.tzinfo is not None
        assert end.tzinfo is not None

    def test_rejects_an_inverted_range(self) -> None:
        """since after until raises rather than silently returning nothing."""
        since = datetime(2026, 8, 2, tzinfo=UTC)
        until = datetime(2026, 8, 1, tzinfo=UTC)

        with pytest.raises(ValueError):
            resolve_window(since, until, None, 24, now=NOW)

    def test_rejects_a_since_in_the_future(self) -> None:
        with pytest.raises(ValueError):
            resolve_window(NOW + timedelta(hours=1), None, None, 24, now=NOW)

    def test_propagates_an_unparseable_window(self) -> None:
        with pytest.raises(ValueError):
            resolve_window(None, None, "7w", 24, now=NOW)

    def test_uses_the_injected_now(self) -> None:
        """Injectable time is what keeps these deterministic without freezing
        the clock globally."""
        _, end = resolve_window(None, None, "1h", 24, now=NOW)

        assert end == NOW

    def test_defaults_now_to_the_current_time(self) -> None:
        before = datetime.now(UTC)

        _, end = resolve_window(None, None, "1h", 24)

        assert before <= end <= datetime.now(UTC)
