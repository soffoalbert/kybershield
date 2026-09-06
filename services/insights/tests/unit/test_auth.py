"""The shared operator-key authentication in `pycommon.auth`.

Covered here rather than in `pycommon` itself, which has no suite of its own:
shared code is exercised through the services that depend on it. The endpoint
side of this — that an unauthenticated call is actually refused — lives in
`tests/integration/test_auth_endpoint.py`.

Mirrors the ingestion service's `apiKeyStore.test.ts`, because the two schemes
are meant to behave identically and a divergence should fail a test rather than
surprise an operator.
"""

from __future__ import annotations

import pytest
from pycommon import ApiKeyStore, extract_bearer_token, parse_api_keys


class TestParseApiKeys:
    def test_maps_a_secret_to_its_client(self) -> None:
        assert parse_api_keys("ops:s3cret") == {"s3cret": "ops"}

    def test_reads_several_entries(self) -> None:
        keys = parse_api_keys("ops:one,dashboard:two")

        assert keys == {"one": "ops", "two": "dashboard"}

    def test_tolerates_whitespace_around_entries(self) -> None:
        """Hand-edited .env files pick up spaces after commas."""
        assert parse_api_keys(" ops : one , dashboard : two ") == {"one": "ops", "two": "dashboard"}

    def test_keeps_colons_inside_a_secret(self) -> None:
        """Only the first colon separates, so a URL- or base64-shaped secret
        survives instead of being silently truncated to its first segment."""
        assert parse_api_keys("ops:a:b:c") == {"a:b:c": "ops"}

    @pytest.mark.parametrize(
        ("raw", "reason"),
        [
            ("no-separator", "not in"),
            (":secret-only", "blank client id"),
            ("client-only:", "blank secret"),
        ],
    )
    def test_rejects_a_malformed_entry(self, raw: str, reason: str) -> None:
        with pytest.raises(ValueError, match=reason):
            parse_api_keys(raw)

    def test_rejects_a_reused_secret(self) -> None:
        """Two clients on one secret makes the mapping ambiguous: the later
        entry would win and the other client's calls would be misattributed."""
        with pytest.raises(ValueError, match="reuses a secret"):
            parse_api_keys("ops:same,dashboard:same")

    def test_names_the_offending_entry_by_position_not_content(self) -> None:
        """The message reaches stderr on a failed boot, and the entry is a
        credential."""
        with pytest.raises(ValueError) as caught:
            parse_api_keys("ops:fine,broken-entry")

        assert "entry 2" in str(caught.value)
        assert "fine" not in str(caught.value)


class TestExtractBearerToken:
    def test_reads_the_token(self) -> None:
        assert extract_bearer_token("Bearer abc123") == "abc123"

    def test_accepts_any_casing_of_the_scheme(self) -> None:
        assert extract_bearer_token("bEaReR abc123") == "abc123"

    def test_tolerates_surrounding_and_repeated_whitespace(self) -> None:
        """Some HTTP clients introduce it, and the token itself never contains
        it, so this is safe to absorb rather than reject."""
        assert extract_bearer_token("  Bearer   abc123  ") == "abc123"

    @pytest.mark.parametrize(
        "header",
        [None, "", "abc123", "Basic abc123", "Bearer", "Bearer   "],
    )
    def test_returns_none_for_anything_else(self, header: str | None) -> None:
        assert extract_bearer_token(header) is None


class TestApiKeyStore:
    @pytest.fixture
    def store(self) -> ApiKeyStore:
        return ApiKeyStore(parse_api_keys("ops:key-one,dashboard:key-two"))

    def test_resolves_a_key_to_its_client(self, store: ApiKeyStore) -> None:
        client = store.resolve("key-one")

        assert client is not None
        assert client.client_id == "ops"

    def test_resolves_each_configured_key_to_its_own_client(self, store: ApiKeyStore) -> None:
        """Guards the non-short-circuiting loop: a key late in the set must
        resolve as readily as the first one."""
        first, second = store.resolve("key-one"), store.resolve("key-two")

        assert first is not None and first.client_id == "ops"
        assert second is not None and second.client_id == "dashboard"

    @pytest.mark.parametrize("presented", ["wrong", "", "key-one-with-a-suffix", "KEY-ONE"])
    def test_refuses_anything_not_configured(self, store: ApiKeyStore, presented: str) -> None:
        assert store.resolve(presented) is None

    def test_refuses_every_key_when_none_are_configured(self) -> None:
        assert ApiKeyStore({}).resolve("key-one") is None
