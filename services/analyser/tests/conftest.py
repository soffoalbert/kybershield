"""Shared fixtures and fakes for the analyser suite.

Rules are pure functions, so almost everything here exists to let a unit test
build one `Event` and one fake context in two lines.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql
from pycommon import AlertDraft, Event, Severity

from analyser.config import AnalyserConfig
from analyser.engine import AnalysisEngine
from analyser.rules import Rule

#: Fixed clock for every built Event. Nothing in the rules or the engine reads
#: wall-clock time, so a constant keeps assertions on `occurred_at` exact.
FIXED_NOW = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

#: Never connected to. Config tests need a syntactically valid required field,
#: not a reachable server.
DUMMY_DATABASE_URL = "postgresql://user:pass@localhost:5432/unused"

#: Deliberately not the database docker-compose points the services at; see
#: :func:`db_url`.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql://kybershield:kybershield@localhost:5432/kybershield_test"
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"


def make_event(
    *,
    event_id: str = "evt-1",
    agent_id: str = "agent-alpha",
    type_: str = "file_read",
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    ingest_seq: int = 1,
    tags: list[str] | None = None,
) -> Event:
    """Build an Event with sensible defaults.

    Keeps each test focused on the one field under test rather than restating
    a full entity.
    """
    payload = payload if payload is not None else {}
    return Event(
        event_id=event_id,
        ingest_seq=ingest_seq,
        agent_id=agent_id,
        occurred_at=occurred_at or FIXED_NOW,
        received_at=occurred_at or FIXED_NOW,
        type=type_,
        payload=payload,
        # Rules only ever read `payload`; `raw` mirrors it so the entity is
        # realistic without a second literal in every test.
        raw=dict(payload),
        tags=tags or [],
        client_id="test-client",
    )


def make_events(count: int, *, type_: str = "file_read", first_seq: int = 1) -> list[Event]:
    """Build `count` events with consecutive ingest_seq, as a batch fetch returns."""
    return [
        make_event(event_id=f"evt-{seq}", ingest_seq=seq, type_=type_)
        for seq in range(first_seq, first_seq + count)
    ]


def make_config(**overrides: Any) -> AnalyserConfig:
    """Build an AnalyserConfig without reading the environment.

    `database_url` is supplied because it is required; every other field takes
    its declared default unless a test overrides it.
    """
    return AnalyserConfig(database_url=DUMMY_DATABASE_URL, **overrides)


def make_draft(event: Event, rule: str, severity: Severity = Severity.LOW) -> AlertDraft:
    """Build the draft a rule would emit for `event`."""
    return AlertDraft(
        event_id=event.event_id,
        agent_id=event.agent_id,
        rule=rule,
        severity=severity,
        summary=f"{rule} fired",
    )


class StubRule:
    """A rule that alerts on every event, or on none when `fires` is False.

    Stands in for a real detection wherever a test is about the engine's
    orchestration rather than about any particular rule's logic.
    """

    description = "stub rule"

    def __init__(self, id: str, *, fires: bool = True) -> None:
        self.id = id
        self.fires = fires
        #: Events seen, in order, so a test can assert a rule ran at all.
        self.seen: list[Event] = []

    def evaluate(self, event: Event, config: AnalyserConfig) -> list[AlertDraft]:
        self.seen.append(event)
        return [make_draft(event, self.id)] if self.fires else []


class BrokenRule:
    """A rule that always raises, to exercise the engine's failure isolation."""

    description = "broken rule"

    def __init__(self, id: str = "broken", message: str = "boom") -> None:
        self.id = id
        self.message = message

    def evaluate(self, event: Event, config: AnalyserConfig) -> list[AlertDraft]:
        raise RuntimeError(self.message)


class FakeAnalysisRepository:
    """In-memory AnalysisRepository for engine unit tests."""

    #: Alerts accepted so far, deduped on (event_id, rule) exactly as the
    #: unique constraint does.
    written: list[AlertDraft]
    cursor: int
    #: When set, insert_alerts_ignore_dupes raises it, to exercise the
    #: "cursor must not advance" path.
    fail_on_insert: Exception | None

    def __init__(self, events: list[Event] | None = None) -> None:
        self.events = sorted(events or [], key=lambda event: event.ingest_seq)
        self.written = []
        self.cursor = 0
        self.fail_on_insert = None
        self._keys: set[tuple[str, str]] = set()

    def fetch_batch_after(self, cursor: int, limit: int) -> list[Event]:
        return [event for event in self.events if event.ingest_seq > cursor][:limit]

    def fetch_batch_since(self, since: datetime | None, limit: int, offset: int) -> list[Event]:
        matching = [
            event
            for event in self.events
            if since is None or event.occurred_at >= since
        ]
        return matching[offset : offset + limit]

    def insert_alerts_ignore_dupes(self, drafts: Sequence[AlertDraft]) -> int:
        if self.fail_on_insert is not None:
            raise self.fail_on_insert
        written = 0
        for draft in drafts:
            key = (draft.event_id, draft.rule)
            if key in self._keys:
                continue
            self._keys.add(key)
            self.written.append(draft)
            written += 1
        return written

    def get_cursor(self) -> int:
        return self.cursor

    def set_cursor(self, seq: int) -> None:
        self.cursor = seq

    def process_batch_atomically(
        self, events: Sequence[Event], drafts: Sequence[AlertDraft], new_cursor: int
    ) -> int:
        # Both writes or neither, mirroring the single transaction in
        # PgAnalysisRepository: a failed insert must leave the cursor put.
        written = self.insert_alerts_ignore_dupes(drafts)
        self.set_cursor(new_cursor)
        return written


def make_engine(
    *rules: Rule,
    events: list[Event] | None = None,
    batch_size: int = 200,
    config: AnalyserConfig | None = None,
) -> AnalysisEngine:
    """Build an engine over a fresh in-memory repository holding `events`.

    A plain function rather than a fixture because every engine test wants a
    different rule set, and reaching the repository through `engine.repo` keeps
    the arrange step to one line.
    """
    return AnalysisEngine(
        rules,
        FakeAnalysisRepository(events),
        config or make_config(),
        batch_size=batch_size,
    )


@pytest.fixture
def config() -> AnalyserConfig:
    """An AnalyserConfig with test-friendly thresholds, built without env vars.

    Rules take this directly, so a rule unit test needs nothing else.
    """
    return make_config()


@pytest.fixture(scope="session")
def db_url() -> str:
    """Test database URL, skipping the test if nothing is listening.

    Points at a database of its own rather than the one docker-compose runs the
    services against: the analyser container polls that database continuously,
    and a background pass writing alerts under a test's feet is unassertable.
    Created and migrated on first use, then reused.
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
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
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
