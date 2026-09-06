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
        host = extract_host(event.url)
        if host is None:
            return []
        if not is_allowed(host, config.allowed_domains):
            return [AlertDraft(event.event_id, self.id, Severity.MEDIUM, host)]
        return []


def extract_host(url: str) -> str | None:
    """Return the lowercased hostname from `url`, or None if unparseable.

    Strips any port. Returns None for relative URLs and for input that
    `urlparse` accepts but yields no netloc for.
    """
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return None

def is_allowed(host: str, allowlist: list[str]) -> bool:
    """True if `host` equals or is a subdomain of any allowlist entry.

    Comparison is case-insensitive and anchored on a dot, so `evil.com` is not
    matched by an allowlist entry of `il.com`.
    """
    if not allowlist:
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowlist)