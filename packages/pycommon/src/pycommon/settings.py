"""Environment-based configuration shared by the Python services.

Settings are validated at import/boot time so a missing DATABASE_URL fails the
container immediately rather than on the first request.
"""

from __future__ import annotations

import logging
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict

from pycommon.auth import ApiKeyStore, parse_api_keys


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

    #: Comma-separated `clientId:secret` pairs authorising the operator APIs.
    #:
    #: Empty by default only so the analyser's CLI, which serves no HTTP, does
    #: not demand a credential to run a backfill from a shell. The HTTP apps
    #: call :meth:`build_api_key_store` at startup, which rejects a blank
    #: value, so a server still cannot come up unauthenticated.
    operator_api_keys: str = ""

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

    def build_api_key_store(self) -> ApiKeyStore:
        """Build the store for `operator_api_keys`.

        Called at startup rather than per request, so a malformed value fails
        the container instead of every authenticated call.

        Raises:
            ValueError: If the value is blank or malformed. Refusing to start
                is the point: the alternative is a service that answers every
                request with 401 and looks like a credential problem, or worse,
                one that starts with an empty key set and is never asked for a
                credential at all.
        """
        if not self.operator_api_keys.strip():
            raise ValueError(
                "OPERATOR_API_KEYS is required to serve the API; "
                'set it to comma-separated "clientId:secret" pairs'
            )
        return ApiKeyStore(parse_api_keys(self.operator_api_keys))


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
