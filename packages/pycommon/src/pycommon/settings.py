"""Environment-based configuration shared by the Python services.

Settings are validated at import/boot time so a missing DATABASE_URL fails the
container immediately rather than on the first request.
"""

from __future__ import annotations

import logging
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Configuration common to every Python service.

    Subclasses add their own fields and inherit the same env parsing rules.
    Values come from the process environment; docker-compose supplies them and
    `.env.example` documents them.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    log_level: str = "info"
    port: int = 8000
    host: str = "0.0.0.0"

    # Connection pool bounds. Small by default: three services share one
    # Postgres and the prototype is not concurrency-bound.
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5

    @property
    def psycopg_conninfo(self) -> str:
        """Return `database_url` in a form psycopg accepts.

        Normalises the `postgres://` scheme that docker-compose and most tools
        emit into the `postgresql://` form libpq expects.
        """
        if self.database_url.startswith("postgres://"):
            return "postgresql://" + self.database_url.removeprefix("postgres://")
        return self.database_url


def configure_logging(level: str) -> None:
    """Configure stdlib logging for a service.

    Emits single-line records to stderr so `docker compose logs` stays
    readable while stdout is left clear for the CLI's JSON reports, which are
    meant to pipe into `jq`.

    Args:
        level: A logging level name, case-insensitive, e.g. "info".

    Raises:
        ValueError: If `level` is not a known level name. Failing at boot is
            better than silently serving at the wrong verbosity.
    """
    resolved = logging.getLevelNamesMapping().get(level.upper())
    if resolved is None:
        raise ValueError(f"unknown log level {level!r}")

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")
    )
    # `force` so a second call (the CLI after the API module imported) replaces
    # the handlers instead of stacking a duplicate onto the root logger.
    logging.basicConfig(level=resolved, handlers=[handler], force=True)
    # psycopg logs every pool checkout at INFO, which drowns the service's own
    # records. Its warnings still matter, so clamp rather than disable.
    logging.getLogger("psycopg").setLevel(max(resolved, logging.WARNING))
