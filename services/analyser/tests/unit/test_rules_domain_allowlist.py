"""DomainAllowlistRule."""

from __future__ import annotations

import pytest


class TestDomainAllowlistRule:
    def test_allows_exact_allowlisted_host(self) -> None:
        """A request to https://github.com/x with github.com allowlisted is
        silent."""
        pytest.skip("TODO: implement")

    def test_allows_subdomain_of_allowlisted_host(self) -> None:
        """api.github.com is covered by an entry of github.com. Requiring every
        subdomain to be listed makes the allowlist unusable in practice."""
        pytest.skip("TODO: implement")

    def test_fires_on_unlisted_host(self) -> None:
        """A request to https://evil.example.com produces one medium alert."""
        pytest.skip("TODO: implement")

    def test_does_not_treat_suffix_collision_as_subdomain(self) -> None:
        """notgithub.com must not be allowed by an entry of github.com. This is
        the bug a naive endswith introduces and is worth pinning."""
        pytest.skip("TODO: implement")

    def test_ignores_port(self) -> None:
        """github.com:8443 is matched against github.com."""
        pytest.skip("TODO: implement")

    def test_host_comparison_is_case_insensitive(self) -> None:
        """GitHub.COM matches an entry of github.com."""
        pytest.skip("TODO: implement")

    def test_empty_allowlist_disables_the_rule(self) -> None:
        """With no allowlist configured the rule stays silent rather than
        flagging every request. Failing open here is deliberate: the noisy
        alternative gets the whole rule muted."""
        pytest.skip("TODO: implement")

    def test_malformed_url_does_not_raise(self) -> None:
        """'not a url' returns [] rather than propagating a parse error."""
        pytest.skip("TODO: implement")

    def test_relative_url_does_not_raise(self) -> None:
        """'/api/v1/things' has no host and returns []."""
        pytest.skip("TODO: implement")

    def test_ignores_missing_url(self) -> None:
        """An http_request with no payload.url returns []."""
        pytest.skip("TODO: implement")

    def test_ignores_non_http_request_event(self) -> None:
        pytest.skip("TODO: implement")

    def test_alert_details_name_the_host_and_method(self) -> None:
        """details carries the host, the full url, and the HTTP method, so the
        alert is actionable without opening the raw event."""
        pytest.skip("TODO: implement")


class TestExtractHost:
    def test_extracts_host_from_https_url(self) -> None:
        pytest.skip("TODO: implement")

    def test_strips_port(self) -> None:
        pytest.skip("TODO: implement")

    def test_lowercases_host(self) -> None:
        pytest.skip("TODO: implement")

    def test_returns_none_for_relative_url(self) -> None:
        pytest.skip("TODO: implement")

    def test_returns_none_for_garbage(self) -> None:
        pytest.skip("TODO: implement")

    def test_handles_userinfo_in_url(self) -> None:
        """http://user:pass@evil.com/ resolves to evil.com, not to the
        userinfo. Getting this wrong would let a URL smuggle past the
        allowlist."""
        pytest.skip("TODO: implement")


class TestIsAllowed:
    def test_exact_match(self) -> None:
        pytest.skip("TODO: implement")

    def test_subdomain_match(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_suffix_collision(self) -> None:
        pytest.skip("TODO: implement")

    def test_rejects_parent_of_allowlisted_host(self) -> None:
        """An entry of api.github.com must not permit github.com."""
        pytest.skip("TODO: implement")
