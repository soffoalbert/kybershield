"""Detects outbound requests to hosts outside the configured allowlist."""

from __future__ import annotations

from pycommon import AlertDraft, Event, Severity

from analyser.rules.base import RuleContext


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

    def evaluate(self, event: Event, ctx: RuleContext) -> list[AlertDraft]:
        """Return one alert if the request host is not allowlisted.

        Ignores non-`http_request` events. A URL that cannot be parsed, or one
        with no host, returns `[]` rather than raising, so a malformed payload
        cannot stall the batch. An empty allowlist disables the rule outright,
        which is safer than the alternative of flagging every request.
        """
        raise NotImplementedError


def extract_host(url: str) -> str | None:
    """Return the lowercased hostname from `url`, or None if unparseable.

    Strips any port. Returns None for relative URLs and for input that
    `urlparse` accepts but yields no netloc for.
    """
    raise NotImplementedError


def is_allowed(host: str, allowlist: list[str]) -> bool:
    """True if `host` equals or is a subdomain of any allowlist entry.

    Comparison is case-insensitive and anchored on a dot, so `evil.com` is not
    matched by an allowlist entry of `il.com`.
    """
    raise NotImplementedError
