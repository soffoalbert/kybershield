"""DomainAllowlistRule."""

from __future__ import annotations

from typing import Any

from pycommon import Event, Severity

from analyser.rules.domain_allowlist import DomainAllowlistRule, extract_host, is_allowed
from tests.conftest import make_config, make_event


def request_event(url: Any, **kwargs: Any) -> Event:
    """An `http_request` event for `url`, the only shape this rule looks at."""
    return make_event(type_="http_request", payload={"url": url}, **kwargs)


def alerts_for(event: Event, allowed: list[str] | None = None) -> list:
    """Run the rule over `event` with `allowed` as the configured allowlist."""
    config = make_config(allowed_domains=allowed if allowed is not None else ["github.com"])
    return DomainAllowlistRule().evaluate(event, config)


class TestDomainAllowlistRule:
    def test_allows_exact_allowlisted_host(self) -> None:
        assert alerts_for(request_event("https://github.com/org/repo")) == []

    def test_allows_subdomain_of_allowlisted_host(self) -> None:
        assert alerts_for(request_event("https://api.github.com/repos")) == []

    def test_fires_on_unlisted_host(self) -> None:
        alerts = alerts_for(request_event("https://evil.example.com/steal"))

        assert len(alerts) == 1
        assert alerts[0].rule == "domain_allowlist"
        assert alerts[0].severity == Severity.MEDIUM

    def test_does_not_treat_suffix_collision_as_subdomain(self) -> None:
        """`notgithub.com` must not pass an allowlist entry of `github.com`."""
        assert len(alerts_for(request_event("https://notgithub.com/"))) == 1

    def test_ignores_port(self) -> None:
        assert alerts_for(request_event("https://github.com:8443/repos")) == []

    def test_host_comparison_is_case_insensitive(self) -> None:
        assert alerts_for(request_event("https://GitHub.COM/org")) == []

    def test_empty_allowlist_disables_the_rule(self) -> None:
        """An unset ALLOWED_DOMAINS must not alert on every single request."""
        assert alerts_for(request_event("https://evil.example.com"), allowed=[]) == []

    def test_malformed_url_does_not_raise(self) -> None:
        assert alerts_for(request_event("not a url")) == []

    def test_relative_url_does_not_raise(self) -> None:
        assert alerts_for(request_event("/api/v1/things")) == []

    def test_ignores_missing_url(self) -> None:
        assert alerts_for(make_event(type_="http_request", payload={})) == []

    def test_ignores_non_string_url(self) -> None:
        assert alerts_for(request_event(1234)) == []

    def test_ignores_non_http_request_event(self) -> None:
        event = make_event(type_="file_read", payload={"url": "https://evil.example.com"})

        assert alerts_for(event) == []

    def test_alert_carries_the_host_and_the_url(self) -> None:
        url = "https://attacker.com/steal"
        alerts = alerts_for(request_event(url, event_id="evt-9", agent_id="agent-beta"))

        alert = alerts[0]
        assert alert.event_id == "evt-9"
        assert alert.agent_id == "agent-beta"
        assert alert.details == {"host": "attacker.com", "url": url}
        assert "attacker.com" in alert.summary


class TestExtractHost:
    def test_extracts_host_from_https_url(self) -> None:
        assert extract_host("https://foo.com/bar") == "foo.com"

    def test_strips_port(self) -> None:
        assert extract_host("https://foo.com:8443/bar") == "foo.com"

    def test_lowercases_host(self) -> None:
        assert extract_host("https://FOO.com/BAR") == "foo.com"

    def test_returns_none_for_relative_url(self) -> None:
        assert extract_host("/api/v1/things") is None

    def test_returns_none_for_garbage(self) -> None:
        assert extract_host("not a url") is None

    def test_ignores_userinfo(self) -> None:
        """`user:pass@` is part of netloc but must not become the host."""
        assert extract_host("http://user:pass@evil.com/") == "evil.com"


class TestIsAllowed:
    def test_exact_match(self) -> None:
        assert is_allowed("github.com", ["github.com"])

    def test_subdomain_match(self) -> None:
        assert is_allowed("api.github.com", ["github.com"])

    def test_rejects_suffix_collision(self) -> None:
        assert not is_allowed("notgithub.com", ["github.com"])

    def test_rejects_parent_of_allowlisted_host(self) -> None:
        """An entry of api.github.com must not permit github.com."""
        assert not is_allowed("github.com", ["api.github.com"])

    def test_an_empty_allowlist_allows_everything(self) -> None:
        assert is_allowed("evil.example.com", [])
