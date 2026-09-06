"""Analyser configuration.

Everything a rule might reasonably need to tune lives here rather than in the
rule bodies, so thresholds and allowlists are operator-adjustable without a
code change. The engine passes it to every rule's `evaluate`.
"""

from __future__ import annotations

from functools import lru_cache

from pycommon import BaseServiceSettings
from pydantic import field_validator


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

    # --- domain_allowlist rule ---
    allowed_domains: list[str] = []

    # --- secret_file_access rule ---
    # Case-insensitive substrings matched against the file path.
    secret_path_patterns: list[str] = [
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

        docker-compose passes `ALLOWED_DOMAINS=a.com,b.com`; pydantic would
        otherwise try to parse that as JSON and fail.
        """
        if isinstance(value, str):
            return value.split(",")
        return value


@lru_cache(maxsize=1)
def get_config() -> AnalyserConfig:
    """Return the process-wide config, parsed once.

    Cached so FastAPI dependencies and the CLI observe the same instance.
    """
    # BaseSettings reads the environment itself; passing `os.environ` as kwargs
    # would hand it uppercase keys that match no field.
    return AnalyserConfig()
