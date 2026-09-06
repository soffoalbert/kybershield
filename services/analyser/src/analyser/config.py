"""Analyser configuration.

Everything a rule might reasonably need to tune lives here rather than in the
rule bodies, so thresholds and allowlists are operator-adjustable without a
code change. The engine passes it to every rule's `evaluate`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from pycommon import BaseServiceSettings
from pydantic import field_validator
from pydantic_settings import NoDecode


class AnalyserConfig(BaseServiceSettings):
    """Environment-driven analyser settings."""

    port: int = 8001

    # --- Poller ---
    # Fallback only. New events normally arrive via LISTEN/NOTIFY, so this is
    # the upper bound on latency when a notification is missed rather than the
    # normal detection latency. Longer than the old push-free default for that
    # reason.
    poll_interval_seconds: float = 30.0
    batch_size: int = 200
    # When false the FastAPI app starts without a poller, so `POST
    # /v1/analyze/run` is the only trigger. Useful in tests.
    poller_enabled: bool = True

    # --- LISTEN/NOTIFY ---
    # Must match the channel in db/migrations/002_notify_on_ingest.sql.
    notify_channel: str = "events_ingested"
    # When false the poller runs on the interval alone. Useful for tests, and
    # an escape hatch if the trigger is ever dropped.
    listen_enabled: bool = True
    listen_reconnect_seconds: float = 5.0

    # `NoDecode` on both list fields below: without it pydantic-settings runs
    # `json.loads` on the raw env value inside its env source, which fails on
    # `a.com,b.com` before any validator gets a chance to split it. NoDecode
    # hands the string through untouched so `_split_csv` can do the work.

    # --- domain_allowlist rule ---
    allowed_domains: Annotated[list[str], NoDecode] = []

    # --- secret_file_access rule ---
    # Case-insensitive substrings matched against the file path.
    secret_path_patterns: Annotated[list[str], NoDecode] = [
        ".env",
        "id_rsa",
        ".aws/credentials",
        ".ssh/",
        ".pem",
        "secrets.yaml",
        ".kube/config",
    ]

    @field_validator("allowed_domains", "secret_path_patterns", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string for list fields.

        docker-compose passes `ALLOWED_DOMAINS=a.com,b.com`. Reachable only
        because the field is annotated `NoDecode`; otherwise the env source
        would have already failed trying to JSON-decode the value.

        Entries are stripped and blanks dropped, so `a.com, b.com` and a
        trailing comma both behave.
        """
        if isinstance(value, str):
            return [entry.strip() for entry in value.split(",") if entry.strip()]
        return value


#: Which settings each rule actually reads. Used by `GET /v1/rules` and the
#: `list-rules` command to show live thresholds. A rule absent from this map,
#: or mapped to an empty list, has nothing to tune.
RULE_CONFIG_FIELDS: dict[str, list[str]] = {
    "domain_allowlist": ["allowed_domains"],
    "secret_file_access": ["secret_path_patterns"],
    "download_and_execute": [],
}


def rule_config(rule_id: str, config: AnalyserConfig) -> dict[str, Any]:
    """Return the settings that affect `rule_id`.

    Whitelisted per rule rather than dumping the whole settings object, which
    would put `database_url` in an unauthenticated response.
    """
    return {field: getattr(config, field) for field in RULE_CONFIG_FIELDS.get(rule_id, [])}


@lru_cache(maxsize=1)
def get_config() -> AnalyserConfig:
    """Return the process-wide config, parsed once.

    Cached so FastAPI dependencies and the CLI observe the same instance.
    """
    # BaseSettings reads the environment itself; passing `os.environ` as kwargs
    # would hand it uppercase keys that match no field.
    return AnalyserConfig()
