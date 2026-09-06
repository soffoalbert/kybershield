"""Environment-based configuration shared by the Python services.

Settings are validated at import/boot time so a missing DATABASE_URL fails the
container immediately rather than on the first request.
"""

from __future__ import annotations

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
        raise NotImplementedError


def configure_logging(level: str) -> None:
    """Configure stdlib logging for a service.

    Emits single-line records to stdout so `docker compose logs` stays
    readable. Silences psycopg's per-query debug chatter.

    Args:
        level: A logging level name, case-insensitive, e.g. "info".
    """
    raise NotImplementedError
