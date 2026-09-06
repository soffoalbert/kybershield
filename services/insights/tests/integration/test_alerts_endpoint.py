"""GET /v1/alerts against a seeded database.

Requires `docker compose up -d postgres`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestDefaultWindow:
    def test_returns_alerts_from_the_last_24_hours(self) -> None:
        """The brief's headline requirement."""
        pytest.skip("TODO: implement")

    def test_excludes_an_alert_older_than_24_hours(self) -> None:
        """Seed one at now - 25h and assert it is absent. The complement of the
        test above, and the one that actually proves the filter runs."""
        pytest.skip("TODO: implement")

    def test_includes_an_alert_just_inside_the_boundary(self) -> None:
        """now - 23h59m is included, pinning the boundary from the other
        side."""
        pytest.skip("TODO: implement")

    def test_orders_newest_first(self) -> None:
        pytest.skip("TODO: implement")

    def test_ordering_is_stable_for_identical_timestamps(self) -> None:
        """Ties break on alert_id, so pagination cannot show the same row twice
        or skip one between pages."""
        pytest.skip("TODO: implement")


class TestFilters:
    def test_filters_by_agent_id(self) -> None:
        pytest.skip("TODO: implement")

    def test_filters_by_rule(self) -> None:
        pytest.skip("TODO: implement")

    def test_filters_by_minimum_severity(self) -> None:
        """severity_min=high returns high and critical only, relying on the
        Postgres enum's ordering."""
        pytest.skip("TODO: implement")

    def test_combines_filters_conjunctively(self) -> None:
        """agent_id and rule together narrow rather than widen."""
        pytest.skip("TODO: implement")

    def test_rejects_an_invalid_severity(self) -> None:
        """severity_min=urgent answers 400, not 500."""
        pytest.skip("TODO: implement")

    def test_accepts_an_explicit_since_and_until(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_an_inverted_range(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_an_unparseable_window(self) -> None:
        pytest.skip("TODO: implement")


class TestPagination:
    def test_respects_limit(self) -> None:
        pytest.skip("TODO: implement")

    def test_respects_offset(self) -> None:
        pytest.skip("TODO: implement")

    def test_total_counts_all_matches_not_just_the_page(self) -> None:
        """What lets a dashboard size its paginator from a single request."""
        pytest.skip("TODO: implement")

    def test_total_reflects_the_active_filters(self) -> None:
        pytest.skip("TODO: implement")

    def test_clamps_limit_to_max_page_size(self) -> None:
        """An oversized limit is clamped rather than rejected: the caller gets
        data instead of an error."""
        pytest.skip("TODO: implement")

    def test_offset_past_the_end_returns_an_empty_page(self) -> None:
        pytest.skip("TODO: implement")

    def test_pages_do_not_overlap_or_skip(self) -> None:
        """Walk every page and assert the union equals the full set exactly
        once."""
        pytest.skip("TODO: implement")


class TestEmptyResults:
    def test_unknown_agent_returns_an_empty_page_not_404(self) -> None:
        """A well-formed question whose answer is "nothing" is a 200. A 404
        would conflate it with a malformed request."""
        pytest.skip("TODO: implement")

    def test_empty_database_returns_an_empty_page(self) -> None:
        pytest.skip("TODO: implement")


class TestResponseShape:
    def test_items_carry_every_documented_field(self) -> None:
        pytest.skip("TODO: implement")

    def test_timestamps_serialise_as_iso_8601_utc(self) -> None:
        pytest.skip("TODO: implement")

    def test_severity_serialises_as_a_lowercase_string(self) -> None:
        pytest.skip("TODO: implement")
