"""DomainAllowlistRule."""

from __future__ import annotations

import pytest
from typing import List, Optional
from urllib.parse import urlparse

# --- Minimal DomainAllowlistRule Implementation ---

def extract_host(url: str) -> Optional[str]:
    """Extract the host (without port, lowercased) from URL or return None."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            return None
        return parsed.hostname.lower()
    except Exception:
        return None

def is_allowed(host: str, allowlist: List[str]) -> bool:
    """Check if host is in allowlist (including subdomains)."""
    host = host.lower()
    for allowed in allowlist:
        allowed = allowed.lower()
        if host == allowed:
            return True
        # matches subdomain, but not suffix collision
        if host.endswith("." + allowed):
            return True
    return False

class DomainAllowlistRule:
    def __init__(self, allowlist: List[str]):
        self.allowlist = [h.lower() for h in allowlist]

    def check(self, event: dict) -> List[dict]:
        if event.get("type") != "http_request":
            return []
        url = event.get("payload", {}).get("url")
        method = event.get("payload", {}).get("method", "GET")
        if not url:
            return []
        host = extract_host(url)
        if not host:
            return []
        if not self.allowlist:
            return []
        if is_allowed(host, self.allowlist):
            return []
        return [{
            "level": "medium",
            "details": f"Blocked HTTP request to host={host} method={method} url={url}"
        }]

# -- Test doubles --

def make_event(url: Optional[str], method: str = "GET"):
    payload = {} if url is None else {"url": url, "method": method}
    return {"type": "http_request", "payload": payload}

# --- TESTS ---

class TestDomainAllowlistRule:
    def test_allows_exact_allowlisted_host(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("https://github.com/x")
        assert rule.check(event) == []

    def test_allows_subdomain_of_allowlisted_host(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("https://api.github.com/stuff")
        assert rule.check(event) == []

    def test_fires_on_unlisted_host(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("https://evil.example.com/bad")
        results = rule.check(event)
        assert len(results) == 1
        assert results[0]["level"] == "medium"
        assert "evil.example.com" in results[0]["details"]

    def test_does_not_treat_suffix_collision_as_subdomain(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("https://notgithub.com/")
        results = rule.check(event)
        assert len(results) == 1
        assert "notgithub.com" in results[0]["details"]

    def test_ignores_port(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("https://github.com:8443/foo")
        assert rule.check(event) == []

    def test_host_comparison_is_case_insensitive(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("https://GitHub.COM/x")
        assert rule.check(event) == []

    def test_empty_allowlist_disables_the_rule(self) -> None:
        rule = DomainAllowlistRule([])
        event = make_event("https://evil.example.com")
        # Should NOT alert; rule is silent when allowlist is empty
        assert rule.check(event) == []

    def test_malformed_url_does_not_raise(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("not a url")
        assert rule.check(event) == []

    def test_relative_url_does_not_raise(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("/api/v1/things")
        assert rule.check(event) == []

    def test_ignores_missing_url(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = {"type": "http_request", "payload": {}}
        assert rule.check(event) == []

    def test_ignores_non_http_request_event(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = {"type": "not_http_request", "payload": {"url": "https://evil.example.com"}}
        assert rule.check(event) == []

    def test_alert_details_name_the_host_and_method(self) -> None:
        rule = DomainAllowlistRule(["github.com"])
        event = make_event("https://attacker.com/steal", "POST")
        results = rule.check(event)
        details = results[0]["details"]
        assert "attacker.com" in details
        assert "POST" in details
        assert "https://attacker.com/steal" in details


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

    def test_handles_userinfo_in_url(self) -> None:
        # host should be just evil.com, not "user:pass@evil.com"
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
