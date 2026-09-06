"""Domain entities shared by the analyser and insights services.

These mirror the tables in db/migrations/001_init.sql. They are plain frozen
dataclasses rather than pydantic models because they are internal domain
objects, not request or response bodies; each service defines its own pydantic
models at its HTTP boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """Alert severity, ordered low to critical.

    Mirrors the Postgres `severity` enum. Declaration order defines the
    ordering used by :meth:`rank` and by MAX(severity) in SQL.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Return a comparable integer where critical is highest.

        Enables sorting and `severity_min` filtering in Python without
        round-tripping to the database.
        """
        # Declaration order is the ordering, so it is the single place a new
        # level has to be inserted correctly.
        return list(type(self)).index(self)

    @classmethod
    def max_of(cls, severities: list[Severity]) -> Severity | None:
        """Return the highest severity in `severities`, or None if empty."""
        return max(severities, key=lambda severity: severity.rank, default=None)


class EventType(StrEnum):
    """Known event types.

    The ingestion service accepts unknown types and stores their payload
    verbatim, so this enum is a convenience for rule authors rather than a
    closed set. Compare against `Event.type` (a plain str) by value.
    """

    HTTP_REQUEST = "http_request"
    FILE_READ = "file_read"
    SHELL_COMMAND = "shell_command"
    TOOL_CALL = "tool_call"


@dataclass(frozen=True)
class Event:
    """One activity event as stored in the `events` table.

    Attributes:
        event_id: Client-supplied identifier; the idempotency key.
        ingest_seq: Monotonic arrival sequence. The analyser's polling cursor
            is expressed in terms of this, never `occurred_at`.
        agent_id: Agent that produced the event.
        occurred_at: When the agent says the activity happened. May be older
            than events with a lower `ingest_seq` (out-of-order arrival).
        received_at: When ingestion persisted the event.
        type: Event type, e.g. `file_read`. Free-form, see :class:`EventType`.
        payload: Validated and normalised event details.
        raw: The exact envelope as submitted, never rewritten.
        tags: Optional client-supplied labels.
        client_id: Which API key submitted the event.
    """

    event_id: str
    ingest_seq: int
    agent_id: str
    occurred_at: datetime
    received_at: datetime
    type: str
    payload: dict[str, Any]
    raw: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    client_id: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Event:
        """Build an Event from a psycopg dict row.

        Expects the column names used in db/migrations/001_init.sql. Raises
        KeyError if a required column is absent, which is intentional: a
        missing column is a query bug, not a runtime condition to tolerate.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class AlertDraft:
    """An alert a rule wants to raise, before it has been persisted.

    Has no `alert_id` or `created_at` because the database assigns both. The
    (event_id, rule) pair is the natural key that makes inserts idempotent.
    """

    event_id: str
    agent_id: str
    rule: str
    severity: Severity
    summary: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class Alert:
    """A persisted alert as stored in the `alerts` table."""

    alert_id: str
    event_id: str
    agent_id: str
    created_at: datetime
    rule: str
    severity: Severity
    summary: str
    details: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Alert:
        """Build an Alert from a psycopg dict row."""
        raise NotImplementedError
