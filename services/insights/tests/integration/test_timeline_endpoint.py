"""GET /v1/agents/{agent_id}/timeline."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestMerging:
    def test_interleaves_events_and_alerts_by_timestamp(self) -> None:
        """The point of the endpoint: seeing an alert land between the events
        that surrounded it."""
        pytest.skip("TODO: implement")

    def test_sets_the_kind_discriminator_correctly(self) -> None:
        pytest.skip("TODO: implement")

    def test_reference_id_is_the_event_id_for_events(self) -> None:
        pytest.skip("TODO: implement")

    def test_reference_id_is_the_alert_id_for_alerts(self) -> None:
        pytest.skip("TODO: implement")

    def test_returns_events_when_the_agent_has_no_alerts(self) -> None:
        pytest.skip("TODO: implement")

    def test_orders_newest_first(self) -> None:
        pytest.skip("TODO: implement")

    def test_ordering_is_stable_for_identical_timestamps(self) -> None:
        """An event and its alert can share a timestamp; the tiebreak keeps the
        output deterministic."""
        pytest.skip("TODO: implement")


class TestBriefText:
    def test_event_brief_names_the_type_and_salient_field(self) -> None:
        """A file_read reads as the path, an http_request as the URL, so the
        timeline is legible without opening each raw event."""
        pytest.skip("TODO: implement")

    def test_alert_brief_is_the_alert_summary(self) -> None:
        pytest.skip("TODO: implement")

    def test_event_brief_survives_a_missing_payload_field(self) -> None:
        """A payload with no recognisable field still yields a usable brief
        rather than raising."""
        pytest.skip("TODO: implement")


class TestSeverityAndRule:
    def test_alerts_carry_severity_and_rule(self) -> None:
        pytest.skip("TODO: implement")

    def test_events_carry_neither(self) -> None:
        pytest.skip("TODO: implement")


class TestScoping:
    def test_excludes_other_agents(self) -> None:
        pytest.skip("TODO: implement")

    def test_applies_the_time_window_to_both_kinds(self) -> None:
        pytest.skip("TODO: implement")

    def test_respects_the_limit(self) -> None:
        pytest.skip("TODO: implement")

    def test_limit_applies_to_the_merged_stream(self) -> None:
        """The reason for UNION ALL over two separate queries: a limit applied
        per-kind could return a page of only events with the interleaved alerts
        pushed off the end, which is exactly the information the endpoint
        exists to show."""
        pytest.skip("TODO: implement")

    def test_unknown_agent_returns_an_empty_list(self) -> None:
        pytest.skip("TODO: implement")
