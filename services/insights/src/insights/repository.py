"""Read-only queries over events and alerts.

Read-only by convention, not by permission: this service shares the same
database credential as the writers. A dedicated read-only role is the obvious
hardening step and is noted in SOLUTION.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pycommon import Database, Severity

from insights.models import AgentSummary, AlertListItem, RuleCount, TimelineItem

#: Alerts in a window with optional filters.
#:
#: Every filter is written as `(%(param)s IS NULL OR column = %(param)s)` so one
#: statement serves all filter combinations. That keeps the SQL in one readable
#: place instead of string-concatenating a WHERE clause, at the cost of a
#: slightly less selective plan.
#:
#: `severity >= %(severity_min)s` relies on the Postgres enum's declaration
#: order, which is why severity is an enum rather than a text column.
LIST_ALERTS_SQL = """
    SELECT alert_id, agent_id, event_id, created_at, rule, severity, summary
      FROM alerts
     WHERE created_at >= %(since)s
       AND created_at <= %(until)s
       AND (%(agent_id)s::text IS NULL OR agent_id = %(agent_id)s)
       AND (%(rule)s::text IS NULL OR rule = %(rule)s)
       AND (%(severity_min)s::severity IS NULL OR severity >= %(severity_min)s)
     ORDER BY created_at DESC, alert_id
     LIMIT %(limit)s OFFSET %(offset)s
"""

#: Companion count for :data:`LIST_ALERTS_SQL`, so `Page.total` is exact.
COUNT_ALERTS_SQL = """
    SELECT count(*) AS total
      FROM alerts
     WHERE created_at >= %(since)s
       AND created_at <= %(until)s
       AND (%(agent_id)s::text IS NULL OR agent_id = %(agent_id)s)
       AND (%(rule)s::text IS NULL OR rule = %(rule)s)
       AND (%(severity_min)s::severity IS NULL OR severity >= %(severity_min)s)
"""

#: Per-agent alert aggregate in one round trip.
#:
#: `max(severity)` is the `anyenum` aggregate, which follows the enum's
#: declaration order, so it returns `critical` over `high` without a CASE ladder.
#:
#: The COALESCEs matter: an agent with no alerts in the window must come back as
#: a zeroed summary rather than a row of nulls, so the endpoint can answer
#: "quiet" instead of a 404.
AGENT_SUMMARY_SQL = """
    WITH per_severity AS (
        SELECT severity, count(*) AS n
          FROM alerts
         WHERE agent_id = %(agent_id)s
           AND created_at >= %(start)s
           AND created_at <= %(end)s
         GROUP BY severity
    )
    SELECT COALESCE(sum(n), 0)::bigint                          AS total_alerts,
           max(severity)                                        AS max_severity,
           COALESCE(jsonb_object_agg(severity::text, n), '{}')  AS severity_counts
      FROM per_severity
"""

#: Event volume for the same window, so alert counts have a denominator.
COUNT_EVENTS_SQL = """
    SELECT count(*) AS total_events
      FROM events
     WHERE agent_id = %(agent_id)s
       AND occurred_at >= %(start)s
       AND occurred_at <= %(end)s
"""

#: Rule frequency for the summary's `top_rules`.
TOP_RULES_SQL = """
    SELECT rule, count(*) AS count
      FROM alerts
     WHERE agent_id = %(agent_id)s
       AND created_at >= %(start)s
       AND created_at <= %(end)s
     GROUP BY rule
     ORDER BY count DESC, rule
     LIMIT %(limit)s
"""

#: Events and alerts merged into one ordered stream.
#:
#: A UNION ALL rather than two queries stitched together in Python, so the
#: LIMIT applies to the merged result and paging cannot return a page that is
#: all events with the interleaved alerts pushed off the end.
#:
#: Events are ordered by `occurred_at` (when the activity happened) and alerts
#: by `created_at` (when it was detected), which is the honest reading of each.
#:
#: An event's `brief` is built here rather than in Python so the query does not
#: have to ship whole payloads back just to extract one field. The COALESCE
#: picks whichever salient key the event type carries, falling back to the bare
#: type for an unknown shape.
AGENT_TIMELINE_SQL = """
    SELECT ts, kind, reference_id, brief, severity, rule
      FROM (
        SELECT occurred_at            AS ts,
               'event'                AS kind,
               event_id               AS reference_id,
               type || COALESCE(
                 ': ' || COALESCE(
                   payload ->> 'path',
                   payload ->> 'url',
                   payload ->> 'command',
                   payload ->> 'name'
                 ), ''
               )                      AS brief,
               NULL::severity         AS severity,
               NULL::text             AS rule
          FROM events
         WHERE agent_id = %(agent_id)s
           AND occurred_at >= %(start)s
           AND occurred_at <= %(end)s
        UNION ALL
        SELECT created_at             AS ts,
               'alert'                AS kind,
               alert_id::text         AS reference_id,
               summary                AS brief,
               severity,
               rule
          FROM alerts
         WHERE agent_id = %(agent_id)s
           AND created_at >= %(start)s
           AND created_at <= %(end)s
      ) merged
     ORDER BY ts DESC, kind, reference_id
     LIMIT %(limit)s OFFSET %(offset)s
"""

#: Companion count for :data:`AGENT_TIMELINE_SQL`, so `Page.total` means the
#: same thing here as it does on the alerts feed: every matching row, not the
#: size of the page just returned.
#:
#: Two counts summed rather than a COUNT(*) over the UNION, which would make
#: Postgres materialise both branches only to discard every column.
COUNT_AGENT_TIMELINE_SQL = """
    SELECT (
        SELECT count(*)
          FROM events
         WHERE agent_id = %(agent_id)s
           AND occurred_at >= %(start)s
           AND occurred_at <= %(end)s
    ) + (
        SELECT count(*)
          FROM alerts
         WHERE agent_id = %(agent_id)s
           AND created_at >= %(start)s
           AND created_at <= %(end)s
    ) AS total
"""


class InsightsRepository(Protocol):
    """Queries backing the insights endpoints."""

    def list_alerts(
        self,
        since: datetime,
        until: datetime,
        agent_id: str | None,
        rule: str | None,
        severity_min: Severity | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlertListItem], int]:
        """Return one page of alerts and the total matching count."""
        ...

    def agent_summary(
        self, agent_id: str, start: datetime, end: datetime, top_rules_limit: int
    ) -> AgentSummary:
        """Return aggregate risk posture for one agent."""
        ...

    def agent_timeline(
        self, agent_id: str, start: datetime, end: datetime, limit: int, offset: int
    ) -> tuple[list[TimelineItem], int]:
        """Return one page of the agent's merged events and alerts, and the
        total number matching the window."""
        ...

    def healthy(self) -> bool:
        """Return True if the database answers. Never raises."""
        ...


class PgInsightsRepository:
    """PostgreSQL implementation of :class:`InsightsRepository`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_alerts(
        self,
        since: datetime,
        until: datetime,
        agent_id: str | None,
        rule: str | None,
        severity_min: Severity | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlertListItem], int]:
        """Run :data:`LIST_ALERTS_SQL` and :data:`COUNT_ALERTS_SQL`.

        An unknown `agent_id` yields an empty page with `total` of 0, not an
        error: the caller asked a well-formed question whose answer is
        "nothing", and 404 would conflate that with a bad request.

        The page and its count share one transaction. On the pool's autocommit
        connections each statement would otherwise take its own snapshot, and
        the analyser writes alerts continuously, so `total` could contradict
        the page it describes.
        """
        params = {
            "since": since,
            "until": until,
            "agent_id": agent_id,
            "rule": rule,
            "severity_min": severity_min.value if severity_min else None,
        }

        with self._db.transaction() as cur:
            rows = cur.execute(
                LIST_ALERTS_SQL, {**params, "limit": limit, "offset": offset}
            ).fetchall()
            count_row = cur.execute(COUNT_ALERTS_SQL, params).fetchone()

        alert_list = [
            AlertListItem(
                alert_id=str(row["alert_id"]),
                agent_id=row["agent_id"],
                event_id=row["event_id"],
                timestamp=row["created_at"],
                rule=row["rule"],
                severity=row["severity"],
                summary=row["summary"],
            )
            for row in rows
        ]
        total = count_row["total"] if count_row else 0

        return alert_list, total

    def agent_summary(
        self, agent_id: str, start: datetime, end: datetime, top_rules_limit: int = 5
    ) -> AgentSummary:
        """Assemble a summary from the aggregate, top-rules, and event-count queries.

        An agent with no alerts in the window returns a populated summary with
        `total_alerts` of 0 and a null `max_severity`, so a dashboard can
        render "quiet" rather than handle a missing response.

        All three statements share one transaction: a summary whose totals,
        top rules, and event count each saw a different snapshot would be
        internally inconsistent for no gain.
        """
        params = {
            "agent_id": agent_id,
            "start": start,
            "end": end,
        }

        with self._db.transaction() as cur:
            agg_row = cur.execute(AGENT_SUMMARY_SQL, params).fetchone()
            event_count_row = cur.execute(COUNT_EVENTS_SQL, params).fetchone()
            top_rules_rows = cur.execute(
                TOP_RULES_SQL, {**params, "limit": top_rules_limit}
            ).fetchall()

        return AgentSummary(
            agent_id=agent_id,
            window_start=start,
            window_end=end,
            total_alerts=agg_row["total_alerts"] if agg_row else 0,
            max_severity=agg_row["max_severity"] if agg_row else None,
            severity_counts=agg_row["severity_counts"] if agg_row else {},
            total_events=event_count_row["total_events"] if event_count_row else 0,
            top_rules=[
                RuleCount(rule=row["rule"], count=row["count"]) for row in top_rules_rows
            ],
        )

    def agent_timeline(
        self, agent_id: str, start: datetime, end: datetime, limit: int, offset: int
    ) -> tuple[list[TimelineItem], int]:
        """Run :data:`AGENT_TIMELINE_SQL` and its companion count.

        Both statements share one repeatable-read transaction so the page and
        the total cannot disagree about how many rows exist, which is otherwise
        possible while the analyser is writing alerts.
        """
        params = {
            "agent_id": agent_id,
            "start": start,
            "end": end,
        }
        with self._db.transaction() as cur:
            rows = cur.execute(
                AGENT_TIMELINE_SQL, {**params, "limit": limit, "offset": offset}
            ).fetchall()
            count_row = cur.execute(COUNT_AGENT_TIMELINE_SQL, params).fetchone()
        timeline = [
            TimelineItem(
                timestamp=row["ts"],
                kind=row["kind"],
                reference_id=row["reference_id"],
                brief=row["brief"],
                severity=row["severity"],
                rule=row["rule"],
            )
            for row in rows
        ]
        return timeline, (count_row["total"] if count_row else 0)

    def healthy(self) -> bool:
        """Delegate to the database health probe."""
        return self._db.healthy()
