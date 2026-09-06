"""Detects reads of files that commonly hold credentials."""

from __future__ import annotations

from pycommon import AlertDraft, Event, Severity

from analyser.config import AnalyserConfig


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

    def evaluate(self, event: Event, config: AnalyserConfig) -> list[AlertDraft]:
        """Return one alert if the path matches any configured pattern.

        Ignores non-`file_read` events and events with a missing or
        non-string `payload.path`. Emits at most one alert regardless of how
        many patterns matched, listing them all in `details.matched_patterns`.
        """
        if event.type != "file_read":
            return []
        if event.payload.path is None or not isinstance(event.payload.path, str):
            return []
        if matches_secret_path(event.payload.path, config.secret_file_patterns):
            return [AlertDraft(event.event_id, self.id, Severity.HIGH, event.payload.path)]
        return []

def matches_secret_path(path: str, patterns: list[str]) -> list[str]:
    """Return the patterns that appear in `path`, compared case-insensitively.

    Split out from the rule so path matching can be tested without building an
    Event.
    """
    return [pattern for pattern in patterns if pattern in path.lower()]
