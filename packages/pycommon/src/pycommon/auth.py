"""API key authentication for the operator-facing services.

A port of the ingestion service's scheme, deliberately: an operator holding a
key should not have to learn a second credential format, and a reviewer
comparing the two should find the same rules. Static keys from the environment,
presented as `Authorization: Bearer <secret>`, compared in constant time,
rejected with `401 {"error": "unauthorized"}`.

The credential *set* is separate, though. Ingestion authenticates agents
submitting events; these services let a caller read every alert in the estate
and trigger re-analysis. Handing agents that reach would mean one compromised
agent key exposes the whole fleet's findings, so this reads `OPERATOR_API_KEYS`
rather than ingestion's `API_KEYS`.

The trade-offs of static keys (long-lived, unrotatable, unscoped, no replay
protection) are the ones documented in SOLUTION.md; the production answer is
the same HMAC-signed request scheme.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.openapi.models import HTTPBearer as HTTPBearerModel
from fastapi.security.base import SecurityBase

__all__ = [
    "ApiKeyStore",
    "ClientIdentity",
    "bearer_scheme",
    "extract_bearer_token",
    "parse_api_keys",
    "require_api_key",
]

logger = logging.getLogger(__name__)

#: `\S+` rather than `.+` so a token never comes back with padding, and a
#: header that is nothing but "Bearer" and spaces fails to match. Leading and
#: trailing whitespace is tolerated because some HTTP clients introduce it.
_BEARER = re.compile(r"^\s*bearer\s+(\S+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ClientIdentity:
    """Who a presented key belongs to."""

    client_id: str


def parse_api_keys(raw: str) -> dict[str, str]:
    """Parse an `OPERATOR_API_KEYS` value into a secret to client id mapping.

    Keyed by secret because lookup happens by presented secret.

    Args:
        raw: Comma-separated `clientId:secret` pairs.

    Returns:
        Secret to client id.

    Raises:
        ValueError: On a malformed entry, a blank client id or secret, or a
            reused secret. Every message names the entry by position rather
            than by content, because this text reaches stderr on a failed boot
            and the entry contains a secret.
    """
    keys: dict[str, str] = {}
    for index, entry in enumerate(raw.split(","), start=1):
        position = f"OPERATOR_API_KEYS entry {index}"

        # Split on the first colon only, so a base64 or URL-shaped secret that
        # contains colons survives intact instead of being silently truncated.
        client_id, separator, secret = entry.strip().partition(":")
        if not separator:
            raise ValueError(f'{position} is not in "clientId:secret" form')

        client_id, secret = client_id.strip(), secret.strip()
        if not client_id:
            raise ValueError(f"{position} has a blank client id")
        if not secret:
            raise ValueError(f"{position} has a blank secret")

        # A reused secret makes the mapping ambiguous: the last entry parsed
        # would win and the other client's requests would be misattributed.
        existing = keys.get(secret)
        if existing:
            raise ValueError(f'{position} reuses a secret already assigned to client "{existing}"')

        keys[secret] = client_id
    return keys


def extract_bearer_token(header: str | None) -> str | None:
    """Pull the token out of an `Authorization` header value.

    Accepts `Bearer <token>` case-insensitively on the scheme.

    Returns:
        The token, or None for a missing header, a non-bearer scheme, or an
        empty token.
    """
    if not header:
        return None
    match = _BEARER.match(header)
    return match.group(1) if match else None


class ApiKeyStore:
    """Resolves presented secrets against a static configured set."""

    def __init__(self, keys: dict[str, str]) -> None:
        """
        Args:
            keys: Secret to client id, as produced by :func:`parse_api_keys`.
        """
        self._keys = keys

    def resolve(self, presented_key: str) -> ClientIdentity | None:
        """Resolve a presented secret to its client.

        Compares against every configured key in constant time and does not
        stop at the first match, so neither the secret's content nor its
        position in the configured set is observable through timing.

        Returns:
            The matching client, or None for an unknown or empty key.
        """
        match: ClientIdentity | None = None
        for key, client_id in self._keys.items():
            # No `break` on a hit, and the result is recorded rather than
            # returned: returning early would make the response time reveal how
            # far down the configured set the matching key sits.
            if _constant_time_equals(presented_key, key):
                match = ClientIdentity(client_id=client_id)
        return match


def _constant_time_equals(a: str, b: str) -> bool:
    """Compare two strings without leaking their contents through timing.

    Both inputs are hashed to a fixed length first, so the comparison cost is
    independent of how much of the secret the caller guessed correctly and
    `compare_digest` never sees operands of differing length. Overall length
    stays coarsely observable through the hashing step, which is acceptable:
    key length is not the secret.
    """
    return hmac.compare_digest(_sha256(a), _sha256(b))


def _sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class _BearerScheme(SecurityBase):
    """Extracts the bearer token and declares the scheme in OpenAPI.

    FastAPI's own `HTTPBearer` would do the second half, but it parses the
    header by splitting on the first space, which disagrees with ingestion
    about padded and repeated whitespace. Since the whole point is that the two
    services accept the same credential presented the same way, extraction goes
    through :func:`extract_bearer_token` and this class exists to put the
    "Authorize" button on `/docs`.
    """

    def __init__(self) -> None:
        self.model = HTTPBearerModel(description="Operator API key")
        self.scheme_name = "OperatorApiKey"

    async def __call__(self, request: Request) -> str | None:
        return extract_bearer_token(request.headers.get("authorization"))


bearer_scheme = _BearerScheme()


async def require_api_key(
    request: Request,
    token: str | None = Depends(bearer_scheme),
) -> ClientIdentity:
    """FastAPI dependency rejecting anything without a valid operator key.

    Resolves against the :class:`ApiKeyStore` the app put on `app.state` at
    startup. Attaches the caller to `request.state.client` so a handler can
    record who asked without re-declaring the dependency.

    Raises:
        HTTPException: 401 for a missing, malformed, or unknown key.

    The response must not distinguish those cases: all three are
    `401 {"error": "unauthorized"}`, so a caller probing the service learns
    nothing about which part of their credential was wrong. The distinction is
    logged, not returned.
    """
    store: ApiKeyStore = request.app.state.api_key_store

    client = store.resolve(token) if token else None
    if client is None:
        logger.warning(
            "rejected unauthenticated request",
            extra={"path": request.url.path, "reason": "no_token" if not token else "unknown_key"},
        )
        # An empty detail rather than a message: the shared handler omits the
        # `issues` key when there is nothing to report, which is what makes
        # this render as the bare `{"error": "unauthorized"}` ingestion sends.
        raise HTTPException(status_code=401, detail=[])

    request.state.client = client
    return client
