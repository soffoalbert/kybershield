"""Harness for the integration suite.

Everything here exists so a test can say "given these events in Postgres, run
a pass, assert on the rows" without repeating connection setup or SQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pycommon import Alert, Database

from analyser.config import get_config
from analyser.engine import AnalysisEngine
from analyser.repository import PgAnalysisRepository
from analyser.rules import Rule, default_rules
from tests.conftest import FIXED_NOW, make_config

#: Emptied before every test. Ordered so the foreign keys are satisfied, and
#: TRUNCATE rather than DELETE so `ingest_seq` restarts and seeded sequence
#: numbers are predictable.
TABLES = ("alerts", "events", "agents")


@pytest.fixture
def db(db_url: str) -> Iterator[Database]:
    """An open Database against the test schema, truncated before each test."""
    database = Database(db_url, application_name="analyser-tests")
    database.open()
    with database.transaction() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        cur.execute("UPDATE analysis_cursor SET last_ingest_seq = 0 WHERE id = 1")
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def repo(db: Database) -> PgAnalysisRepository:
    """The real repository, so the tests exercise the SQL under test."""
    return PgAnalysisRepository(db)


@pytest.fixture
def make_engine(repo: PgAnalysisRepository):
    """Build an engine over the test database.

    Defaults to the shipped rule set, since most of these tests are about the
    pipeline end to end; pass rules explicitly when the test is about the
    engine's behaviour rather than a detection.
    """

    def _make(*rules: Rule, batch_size: int = 200) -> AnalysisEngine:
        return AnalysisEngine(
            rules or default_rules(),
            repo,
            make_config(allowed_domains=["github.com"]),
            batch_size=batch_size,
        )

    return _make


@pytest.fixture
def engine(make_engine) -> AnalysisEngine:
    """An engine with the shipped rules, which is what most tests want."""
    return make_engine()


def seed_event(
    db: Database,
    *,
    event_id: str = "evt-1",
    agent_id: str = "agent-alpha",
    type_: str = "file_read",
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> int:
    """Insert one event, creating its agent, and return its `ingest_seq`.

    `ingest_seq` is assigned by the database rather than passed in: arrival
    order being the database's business, not the caller's, is precisely what
    the out-of-order tests rely on.
    """
    payload = payload if payload is not None else {}
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO agents (agent_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (agent_id,),
        )
        row = cur.execute(
            """
            INSERT INTO events (event_id, agent_id, occurred_at, type, payload, raw, client_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'test-client')
            RETURNING ingest_seq
            """,
            (
                event_id,
                agent_id,
                occurred_at or FIXED_NOW,
                type_,
                Jsonb(payload),
                Jsonb(payload),
            ),
        ).fetchone()
    return row["ingest_seq"]


def seed_secret_read(db: Database, **kwargs: Any) -> int:
    """Insert an event that the shipped rules alert on exactly once."""
    return seed_event(db, type_="file_read", payload={"path": "/app/.env"}, **kwargs)


def read_alerts(db: Database) -> list[Alert]:
    """Return every alert row, ordered as the analyser wrote them."""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT a.alert_id, a.event_id, a.agent_id, a.created_at, a.rule,
                   a.severity, a.summary, a.details
              FROM alerts a
              JOIN events e USING (event_id)
             ORDER BY e.ingest_seq, a.rule
            """
        ).fetchall()
    return [Alert(**row) for row in rows]


def read_cursor(db: Database) -> int:
    """Return the persisted watermark."""
    with db.connection() as conn:
        row = conn.execute("SELECT last_ingest_seq FROM analysis_cursor WHERE id = 1").fetchone()
    return row["last_ingest_seq"]


def set_cursor(db: Database, seq: int) -> None:
    """Move the persisted watermark, to set up a test's starting position."""
    with db.transaction() as cur:
        cur.execute("UPDATE analysis_cursor SET last_ingest_seq = %s WHERE id = 1", (seq,))


@pytest.fixture
def client(db: Database, db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An HTTP client against the real app, wired to the test database.

    Depends on `db` so the tables are truncated before the app opens its own
    pool. The poller and the listener are off, so a pass happens only when a
    test asks for one and assertions are not racing a background loop.
    """
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("POLLER_ENABLED", "false")
    monkeypatch.setenv("LISTEN_ENABLED", "false")
    monkeypatch.setenv("ALLOWED_DOMAINS", "github.com")
    # The app reads its config through an lru_cache, so a cached instance from
    # another test would point the app at the wrong database.
    get_config.cache_clear()

    from analyser.api import create_app

    # As a context manager, so the lifespan opens the pool and starts nothing
    # else, and closes it again on the way out.
    with TestClient(create_app()) as test_client:
        yield test_client

    get_config.cache_clear()


@pytest.fixture
def polling_client(db: Database, db_url: str, monkeypatch: pytest.MonkeyPatch):
    """A client for the app as production runs it: poller and listener on.

    The interval is long, so any pass a test observes came from the wiring
    under test rather than from the fallback timer.
    """
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("POLLER_ENABLED", "true")
    monkeypatch.setenv("LISTEN_ENABLED", "true")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "30")
    get_config.cache_clear()

    from analyser.api import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_config.cache_clear()
