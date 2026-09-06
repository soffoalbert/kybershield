"""Storage access for the analysis pipeline.

The protocol exists so the engine can be unit tested against an in-memory fake
while the Postgres implementation is covered by integration tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from psycopg.types.json import Jsonb
from pycommon import AlertDraft, Database, Event

#: Claim the next batch of events by arrival order.
#:
#: Ordering by `ingest_seq` rather than `occurred_at` is the crux of
#: out-of-order handling: a late event carrying yesterday's timestamp still
#: receives a fresh high sequence number, so it lands after the cursor and is
#: picked up on the next pass. Ordering by time would skip it forever.
FETCH_BATCH_SQL = """
    SELECT event_id, ingest_seq, agent_id, occurred_at, received_at,
           type, payload, raw, tags, client_id
      FROM events
     WHERE ingest_seq > %(cursor)s
     ORDER BY ingest_seq
     LIMIT %(limit)s
"""

#: Backfill page. Filtered on `occurred_at` rather than `ingest_seq` because a
#: backfill is expressed in wall-clock terms ("re-check the last week"), and
#: ordered so LIMIT/OFFSET paging is stable across calls.
FETCH_BATCH_SINCE_SQL = """
    SELECT event_id, ingest_seq, agent_id, occurred_at, received_at,
           type, payload, raw, tags, client_id
      FROM events
     WHERE (%(since)s::timestamptz IS NULL OR occurred_at >= %(since)s)
     ORDER BY ingest_seq
     LIMIT %(limit)s OFFSET %(offset)s
"""

#: Insert alerts, skipping any that already exist for this (event, rule) pair.
#: This is what makes re-analysis and backfill safe to run repeatedly.
INSERT_ALERTS_SQL = """
    INSERT INTO alerts (event_id, agent_id, rule, severity, summary, details)
    VALUES (%(event_id)s, %(agent_id)s, %(rule)s, %(severity)s, %(summary)s, %(details)s)
    ON CONFLICT (event_id, rule) DO NOTHING
    RETURNING alert_id
"""

#: Single-row watermark table, seeded by the migration, so this always matches.
SELECT_CURSOR_SQL = "SELECT last_ingest_seq FROM analysis_cursor WHERE id = 1"

#: Upsert rather than UPDATE so a truncated cursor table heals itself instead
#: of silently never advancing.
UPSERT_CURSOR_SQL = """
    INSERT INTO analysis_cursor (id, last_ingest_seq, updated_at)
    VALUES (1, %(seq)s, now())
    ON CONFLICT (id) DO UPDATE
        SET last_ingest_seq = EXCLUDED.last_ingest_seq,
            updated_at      = EXCLUDED.updated_at
"""


def _alert_params(draft: AlertDraft) -> dict[str, Any]:
    """Bind one draft for :data:`INSERT_ALERTS_SQL`.

    `severity` goes as its plain string value for Postgres to cast to the enum,
    and `details` is wrapped in `Jsonb` so psycopg adapts the dict rather than
    rejecting it.
    """
    return {
        "event_id": draft.event_id,
        "agent_id": draft.agent_id,
        "rule": draft.rule,
        "severity": draft.severity.value,
        "summary": draft.summary,
        "details": Jsonb(draft.details) if draft.details is not None else None,
    }


class AnalysisRepository(Protocol):
    """Everything the engine needs from storage."""

    def fetch_batch_after(self, cursor: int, limit: int) -> list[Event]:
        """Return up to `limit` events with `ingest_seq` above `cursor`.

        Ordered by `ingest_seq` ascending, so the caller can advance the cursor
        to the last element's sequence number.
        """
        ...

    def fetch_batch_since(self, since: datetime | None, limit: int, offset: int) -> list[Event]:
        """Return events for a backfill, filtered by `occurred_at` when given.

        Separate from :meth:`fetch_batch_after` because backfill walks history
        by time and must not disturb the live cursor.
        """
        ...

    def insert_alerts_ignore_dupes(self, drafts: Sequence[AlertDraft]) -> int:
        """Persist drafts, skipping ones already recorded.

        @returns The number of alerts actually written, which is what
        distinguishes a first analysis from a replay in the run report.
        """
        ...

    def get_cursor(self) -> int:
        """Return the highest `ingest_seq` processed so far, 0 if never run."""
        ...

    def set_cursor(self, seq: int) -> None:
        """Move the watermark to `seq`.

        Must be callable inside the same transaction as the alert inserts, so a
        crash between the two cannot lose or double-count work.
        """
        ...

    def process_batch_atomically(
        self, events: Sequence[Event], drafts: Sequence[AlertDraft], new_cursor: int
    ) -> int:
        """Write alerts and advance the cursor in one transaction.

        On the protocol because :meth:`AnalysisEngine.run_once` depends on the
        atomicity, so a fake that skips it is not a valid substitute.

        @returns The number of alerts written.
        """
        ...


class PgAnalysisRepository:
    """PostgreSQL implementation of :class:`AnalysisRepository`."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def fetch_batch_after(self, cursor: int, limit: int) -> list[Event]:
        """Run :data:`FETCH_BATCH_SQL` and map rows to Events."""
        with self.db.connection() as conn:
            rows = conn.execute(FETCH_BATCH_SQL, {"cursor": cursor, "limit": limit}).fetchall()
        return [Event.from_row(row) for row in rows]

    def fetch_batch_since(self, since: datetime | None, limit: int, offset: int) -> list[Event]:
        """Page through history by `occurred_at` for a backfill."""
        params = {"since": since, "limit": limit, "offset": offset}
        with self.db.connection() as conn:
            rows = conn.execute(FETCH_BATCH_SINCE_SQL, params).fetchall()
        return [Event.from_row(row) for row in rows]

    def insert_alerts_ignore_dupes(self, drafts: Sequence[AlertDraft]) -> int:
        """Insert all drafts in one transaction, counting returned ids.

        `details` is serialised to JSON; `severity` is passed as its string
        value so Postgres casts it to the enum.

        Counted from the rows RETURNING gives back rather than from `rowcount`:
        a draft skipped by ON CONFLICT returns nothing, which is exactly the
        "already known finding" case the count must exclude.
        """
        if not drafts:
            return 0
        written = 0
        with self.db.transaction() as cur:
            for draft in drafts:
                cur.execute(INSERT_ALERTS_SQL, _alert_params(draft))
                if cur.fetchone() is not None:
                    written += 1
        return written

    def get_cursor(self) -> int:
        """Read `analysis_cursor.last_ingest_seq`."""
        with self.db.connection() as conn:
            row = conn.execute(SELECT_CURSOR_SQL).fetchone()
        # The migration seeds the row, so None means someone truncated the
        # table. Starting from 0 re-analyses history, which dedupe absorbs.
        return row["last_ingest_seq"] if row else 0

    def set_cursor(self, seq: int) -> None:
        """Write `analysis_cursor.last_ingest_seq` and bump `updated_at`."""
        with self.db.transaction() as cur:
            cur.execute(UPSERT_CURSOR_SQL, {"seq": seq})

    def process_batch_atomically(
        self, events: Sequence[Event], drafts: Sequence[AlertDraft], new_cursor: int
    ) -> int:
        """Write alerts and advance the cursor in one transaction.

        The atomicity that matters: if the insert fails the cursor does not
        move, so the batch is retried rather than silently skipped. If the
        process dies after commit, the alert unique constraint absorbs any
        replay.

        `events` is unused: it is in the signature so an implementation that
        needs the batch (to stamp provenance, say) does not change the port.

        @returns The number of alerts written.
        """
        written = 0
        # One transaction spanning both writes. This is the whole point of the
        # method: separate commits would let a crash advance the cursor past
        # events whose alerts were never stored.
        with self.db.transaction() as cur:
            for draft in drafts:
                cur.execute(INSERT_ALERTS_SQL, _alert_params(draft))
                if cur.fetchone() is not None:
                    written += 1
            cur.execute(UPSERT_CURSOR_SQL, {"seq": new_cursor})
        return written
