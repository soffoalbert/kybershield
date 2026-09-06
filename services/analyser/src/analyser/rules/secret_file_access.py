"""Detects reads of files that commonly hold credentials."""

from __future__ import annotations

from pycommon import AlertDraft, Event, Severity

from analyser.rules.base import RuleContext


class SecretFileAccessRule:
    """Flags `file_read` events whose path looks credential-bearing.

    Matches configured substrings (`.env`, `id_rsa`, `.aws/credentials`,
    `.ssh/`, `.pem`, ...) case-insensitively against the path. Substring
    matching over path parsing is deliberate: it catches `/app/.env.production`
    and `/backups/id_rsa.bak`, which an exact-basename check would miss.

    Severity is `high` rather than `critical` because reading a secret is
    strong evidence of intent but not yet evidence of exfiltration.
    """

    id = "secret_file_access"
    description = "Read of a file whose path suggests it holds credentials"

    def evaluate(self, event: Event, ctx: RuleContext) -> list[AlertDraft]:
        """Return one alert if the path matches any configured pattern.

        Ignores non-`file_read` events and events with a missing or
        non-string `payload.path`. Emits at most one alert regardless of how
        many patterns matched, listing them all in `details.matched_patterns`.
        """
        raise NotImplementedError


def matches_secret_path(path: str, patterns: list[str]) -> list[str]:
    """Return the patterns that appear in `path`, compared case-insensitively.

    Split out from the rule so path matching can be tested without building an
    Event.
    """
    raise NotImplementedError
