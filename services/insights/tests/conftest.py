"""Fixtures for the insights suite.

Almost every test here needs a populated database, since the value of this
service is entirely in its SQL.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from pycommon import Database, Severity


@pytest.fixture(scope="session")
def db_url() -> str:
    """Test database URL, skipping the suite if nothing is listening."""
    raise NotImplementedError


@pytest.fixture
def db(db_url: str) -> Database:
    """An open Database, truncated before each test."""
    raise NotImplementedError


@pytest.fixture
def now() -> datetime:
    """A fixed 'now' so window boundary assertions are deterministic.

    Every seeded row is positioned relative to this, which is what keeps
    "older than 24h" tests from flaking near midnight or on a slow machine.
    """
    raise NotImplementedError


def seed_agent(db: Database, agent_id: str, *, first_seen: datetime, last_seen: datetime) -> None:
    """Insert an agents row."""
    raise NotImplementedError


def seed_event(
    db: Database,
    *,
    event_id: str,
    agent_id: str,
    occurred_at: datetime,
    type_: str = "file_read",
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert one events row, creating the agent if needed."""
    raise NotImplementedError


def seed_alert(
    db: Database,
    *,
    event_id: str,
    agent_id: str,
    rule: str,
    severity: Severity,
    created_at: datetime,
    summary: str = "test alert",
) -> str:
    """Insert one alerts row and return its id.

    `created_at` is explicit rather than defaulted, because window filtering is
    what most of these tests are actually about.
    """
    raise NotImplementedError


@pytest.fixture
def seeded(db: Database, now: datetime) -> dict[str, Any]:
    """A small fixed dataset spanning the 24h boundary.

    Two agents, events and alerts of several severities and rules, with at
    least one alert deliberately older than 24 hours so the default window can
    be shown to exclude it.
    """
    raise NotImplementedError


@pytest.fixture
def client(db: Database):
    """An httpx client against the FastAPI app, wired to the test database."""
    raise NotImplementedError
