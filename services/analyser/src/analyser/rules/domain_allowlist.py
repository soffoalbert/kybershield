"""Detects outbound requests to hosts outside the configured allowlist."""

from __future__ import annotations

from urllib.parse import urlparse

from pycommon import AlertDraft, Event, Severity

from analyser.config import AnalyserConfig


class DomainAllowlistRule:
    """Flags `http_request` events whose host is not on the allowlist.

    An allowlist entry covers that host and its subdomains: `github.com`
    permits `api.github.com`. Suffix matching is anchored on a dot boundary so
    `notgithub.com` does not slip through a naive `endswith`.

    Severity is `medium`: an unlisted domain is frequently benign in
    development, and an allowlist that pages at `high` gets muted.
    """

    id = "domain_allowlist"
    description = "HTTP request to a host outside the configured allowlist"

    def evaluate(self, event: Event, config: AnalyserConfig) -> list[AlertDraft]:
        """Return one alert if the request host is not allowlisted.

        Ignores non-`http_request` events. A URL that cannot be parsed, or one
        with no host, returns `[]` rather than raising, so a malformed payload
        cannot stall the batch. An empty allowlist disables the rule outright,
        which is safer than the alternative of flagging every request.
        """
        if event.type != "http_request":
            return []
        url = event.payload.get("url")
        if not isinstance(url, str):
            return []
        host = extract_host(url)
        if host is None:
            return []
        if is_allowed(host, config.allowed_domains):
            return []

        return [
            AlertDraft(
                event_id=event.event_id,
                agent_id=event.agent_id,
                rule=self.id,
                severity=Severity.MEDIUM,
                summary=f"Agent made an HTTP request to {host}, which is not on the allowlist",
                details={"host": host, "url": url},
            )
        ]


def extract_host(url: str) -> str | None:
    """Return the lowercased hostname from `url`, or None if unparseable.

    Strips any port. Returns None for relative URLs and for input that
    `urlparse` accepts but yields no netloc for.
    """
    try:
        # `hostname`, not `netloc`: netloc keeps the port and any `user:pass@`
        # prefix, so `github.com:443` would never match an allowlist entry.
        host = urlparse(url).hostname
    except ValueError:
        return None
    # A relative URL parses fine but yields no host.
    return host.lower() if host else None


def is_allowed(host: str, allowlist: list[str]) -> bool:
    """True if `host` equals or is a subdomain of any allowlist entry.

    Comparison is case-insensitive and anchored on a dot, so `evil.com` is not
    matched by an allowlist entry of `il.com`.

    An empty allowlist means the rule is not configured, so everything is
    allowed. Treating it as "nothing is allowed" would alert on every single
    request the moment an operator forgot to set `ALLOWED_DOMAINS`.
    """
    if not allowlist:
        return True
    host = host.lower()
    return any(
        host == entry or host.endswith(f".{entry}")
        for entry in (allowed.lower() for allowed in allowlist)
    )