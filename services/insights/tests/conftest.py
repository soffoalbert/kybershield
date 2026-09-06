"""Fixtures for the insights suite.

Almost every test here needs a populated database, since the value of this
service is entirely in its SQL.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb
from pycommon import Database, Severity

from insights.config import get_config

#: Deliberately not the database docker-compose points the services at: the
#: analyser container writes to that one continuously, and rows appearing under
#: a test's feet are unassertable.
#:
#: Suffixed per suite rather than a shared `kybershield_test`: every suite
#: truncates between tests, so two running at once wipe each other's fixtures
#: and fail in ways that look like product bugs rather than interference.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql://kybershield:kybershield@localhost:5432/kybershield_test_insights"
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"

#: Emptied before every test. Ordered so the foreign keys are satisfied.
TABLES = ("alerts", "events", "agents")

#: Supplies unique `event_id` values across a session, so a test that seeds
#: several alerts does not have to invent ids the (event_id, rule) constraint
#: will accept.
_ids = count(1)


@pytest.fixture(scope="session")
def db_url() -> str:
    """Test database URL, skipping the suite if nothing is listening.

    Created and migrated on first use, then reused, so a checkout needs only
    `docker compose up -d postgres` before `pytest`.
    """
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        _create_database_if_absent(url)
        with psycopg.connect(url, connect_timeout=3) as conn:
            _apply_migrations_if_absent(conn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"no PostgreSQL for the integration suite: {exc}")
    return url


def _create_database_if_absent(url: str) -> None:
    """CREATE DATABASE for `url` if it does not exist yet.

    Connects to the server's default `postgres` database to do it, since one
    cannot create a database from inside itself.
    """
    parsed = urlsplit(url)
    name = parsed.path.lstrip("/")
    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    # autocommit: CREATE DATABASE cannot run inside a transaction block.
    with psycopg.connect(admin_url, connect_timeout=3, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _apply_migrations_if_absent(conn: psycopg.Connection) -> None:
    """Run db/migrations against a freshly created database.

    Keyed on the `events` table rather than on a migrations ledger: there is no
    migration tool in this prototype, the files are the schema, and re-running
    them on an already-migrated database would fail on the CREATE TYPE.
    """
    migrated = conn.execute("SELECT to_regclass('public.events')").fetchone()
    if migrated is not None and migrated[0] is not None:
        return
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.execute(path.read_text())
    conn.commit()


@pytest.fixture
def db(db_url: str) -> Iterator[Database]:
    """An open Database, truncated before each test."""
    database = Database(db_url, application_name="insights-tests")
    database.open()
    with database.transaction() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def now() -> datetime:
    """A fixed 'now' so window boundary assertions are deterministic.

    Every seeded row is positioned relative to this, which is what keeps
    "older than 24h" tests from flaking near midnight or on a slow machine.

    Real current time rather than a constant, because the endpoints resolve
    their default window against the clock at request time: a seeded row has to
    be recent in absolute terms to fall inside it.
    """
    return datetime.now(UTC)


def seed_agent(db: Database, agent_id: str, *, first_seen: datetime, last_seen: datetime) -> None:
    """Insert an agents row."""
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO agents (agent_id, first_seen_at, last_seen_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (agent_id) DO UPDATE
                SET first_seen_at = LEAST(agents.first_seen_at, EXCLUDED.first_seen_at),
                    last_seen_at  = GREATEST(agents.last_seen_at, EXCLUDED.last_seen_at)
            """,
            (agent_id, first_seen, last_seen),
        )


def seed_event(
    db: Database,
    *,
    event_id: str | None = None,
    agent_id: str = "agent-alpha",
    occurred_at: datetime | None = None,
    type_: str = "file_read",
    payload: dict[str, Any] | None = None,
) -> str:
    """Insert one events row, creating the agent if needed.

    Returns the event id, generated when the caller does not care what it is.
    """
    event_id = event_id or f"evt-{next(_ids)}"
    occurred_at = occurred_at or datetime.now(UTC)
    payload = payload if payload is not None else {"path": "/app/.env"}

    seed_agent(db, agent_id, first_seen=occurred_at, last_seen=occurred_at)
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO events (event_id, agent_id, occurred_at, type, payload, raw, client_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'test-client')
            """,
            (event_id, agent_id, occurred_at, type_, Jsonb(payload), Jsonb(payload)),
        )
    return event_id


def seed_alert(
    db: Database,
    *,
    event_id: str | None = None,
    agent_id: str = "agent-alpha",
    rule: str = "secret_file_access",
    severity: Severity = Severity.HIGH,
    created_at: datetime | None = None,
    summary: str = "test alert",
) -> str:
    """Insert one alerts row and return its id.

    `created_at` is explicit rather than defaulted, because window filtering is
    what most of these tests are actually about.

    An event is seeded to hang the alert off when the caller does not name one:
    alerts have foreign keys to both `events` and `agents`, and most alert tests
    have no opinion about the underlying activity.
    """
    created_at = created_at or datetime.now(UTC)
    if event_id is None:
        event_id = seed_event(db, agent_id=agent_id, occurred_at=created_at)

    with db.transaction() as cur:
        row = cur.execute(
            """
            INSERT INTO alerts (event_id, agent_id, created_at, rule, severity, summary)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING alert_id
            """,
            (event_id, agent_id, created_at, rule, severity.value, summary),
        ).fetchone()
    return str(row["alert_id"])


@pytest.fixture
def seeded(db: Database, now: datetime) -> dict[str, Any]:
    """A small fixed dataset spanning the 24h boundary.

    Two agents, events and alerts of several severities and rules, with at
    least one alert deliberately older than 24 hours so the default window can
    be shown to exclude it.

    Alert ids come back newest first, matching the order every endpoint returns
    them in, so a test can assert on the list directly.
    """
    alpha, beta = "agent-alpha", "agent-beta"

    alpha_recent = [
        seed_alert(
            db,
            agent_id=alpha,
            rule="domain_allowlist",
            severity=Severity.MEDIUM,
            created_at=now - timedelta(hours=1),
            summary="request to evil.example.com",
        ),
        seed_alert(
            db,
            agent_id=alpha,
            rule="secret_file_access",
            severity=Severity.HIGH,
            created_at=now - timedelta(hours=2),
            summary="read /app/.env",
        ),
        seed_alert(
            db,
            agent_id=alpha,
            rule="download_and_execute",
            severity=Severity.CRITICAL,
            created_at=now - timedelta(hours=3),
            summary="curl piped to bash",
        ),
    ]
    beta_recent = [
        seed_alert(
            db,
            agent_id=beta,
            rule="secret_file_access",
            severity=Severity.LOW,
            created_at=now - timedelta(minutes=30),
            summary="read /home/beta/.ssh/id_rsa",
        )
    ]
    # Outside the 24h default, and `critical` so a test can prove the window
    # bounds `max_severity` too rather than only the row count.
    alpha_old = seed_alert(
        db,
        agent_id=alpha,
        rule="download_and_execute",
        severity=Severity.CRITICAL,
        created_at=now - timedelta(hours=25),
        summary="stale finding",
    )

    return {
        "now": now,
        "alpha": alpha,
        "beta": beta,
        #: Newest first, as the endpoints order them.
        "recent": [beta_recent[0], *alpha_recent],
        "alpha_recent": alpha_recent,
        "beta_recent": beta_recent,
        "alpha_old": alpha_old,
    }


@pytest.fixture
def client(db: Database, db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An httpx client against the FastAPI app, wired to the test database.

    Depends on `db` so the tables are truncated before the app opens its own
    pool. Every other setting keeps its declared default, so what the tests
    exercise is the shipped configuration.
    """
    monkeypatch.setenv("DATABASE_URL", db_url)
    # The app reads its config through an lru_cache, so a cached instance from
    # another test would point it at the wrong database.
    get_config.cache_clear()

    from insights.api import create_app

    # As a context manager, so the lifespan opens the pool and closes it again.
    with TestClient(create_app()) as test_client:
        yield test_client

    get_config.cache_clear()
