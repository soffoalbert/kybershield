"""Shared fixtures and fakes for the analyser suite.

Rules are pure functions, so almost everything here exists to let a unit test
build one `Event` and one fake context in two lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import pytest
from pycommon import AlertDraft, Event

from analyser.config import AnalyserConfig


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
    raise NotImplementedError


class FakeAnalysisRepository:
    """In-memory AnalysisRepository for engine unit tests."""

    def __init__(self, events: list[Event] | None = None) -> None:
        raise NotImplementedError

    #: Alerts accepted so far, deduped on (event_id, rule) exactly as the
    #: unique constraint does.
    written: list[AlertDraft]
    cursor: int
    #: When set, insert_alerts_ignore_dupes raises it, to exercise the
    #: "cursor must not advance" path.
    fail_on_insert: Exception | None

    def fetch_batch_after(self, cursor: int, limit: int) -> list[Event]: ...
    def fetch_batch_since(self, since: datetime | None, limit: int, offset: int) -> list[Event]: ...
    def insert_alerts_ignore_dupes(self, drafts: Sequence[AlertDraft]) -> int: ...
    def get_cursor(self) -> int: ...
    def set_cursor(self, seq: int) -> None: ...
    def process_batch_atomically(
        self, events: Sequence[Event], drafts: Sequence[AlertDraft], new_cursor: int
    ) -> int: ...


@pytest.fixture
def config() -> AnalyserConfig:
    """An AnalyserConfig with test-friendly thresholds, built without env vars.

    Rules take this directly, so a rule unit test needs nothing else.
    """
    raise NotImplementedError


@pytest.fixture
def db_url() -> str:
    """Test database URL, skipping the test if nothing is listening."""
    raise NotImplementedError
