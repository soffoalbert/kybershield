"""Response models.

Pydantic rather than the shared dataclasses because these are the public
contract: they generate the OpenAPI schema a teammate would build a dashboard
against. Every list response is wrapped in :class:`Page` so pagination is
uniform and a client never has to guess whether more data exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar, Any

from pycommon import Severity
from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A slice of a larger result set."""

    items: list[T]
    #: Total matching rows ignoring limit/offset, so a UI can size a paginator.
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        """True if rows remain beyond this page."""
        # True if there are more matching rows than this page shows
        return self.offset + self.limit < self.total if self.limit is not None else False


class AlertListItem(BaseModel):
    """One row in the alerts feed."""

    alert_id: str
    agent_id: str
    event_id: str
    #: Alert creation time. Distinct from the event's `occurred_at`, which the
    #: timeline exposes; keeping them separate avoids implying the analyser saw
    #: the activity the moment it happened.
    timestamp: datetime
    rule: str
    severity: Severity
    summary: str

    def __init__(
        self,
        alert_id: str,
        agent_id: str,
        event_id: str,
        timestamp: datetime,
        rule: str,
        severity: Severity,
        summary: str,
        **data: Any,
    ):
        super().__init__(
            alert_id=alert_id,
            agent_id=agent_id,
            event_id=event_id,
            timestamp=timestamp,
            rule=rule,
            severity=severity,
            summary=summary,
            **data,
        )


class RuleCount(BaseModel):
    """A rule and how often it fired within a window."""

    rule: str
    count: int

    def __init__(
        self,
        rule: str,
        count: int,
        **data: Any,
    ):
        super().__init__(rule=rule, count=count, **data)


class AgentSummary(BaseModel):
    """Risk posture for one agent over a time window."""

    agent_id: str
    window_start: datetime
    window_end: datetime
    total_alerts: int
    #: Null when the agent produced no alerts in the window.
    max_severity: Severity | None = None
    top_rules: list[RuleCount] = Field(default_factory=list)
    #: Alert count per severity, so a dashboard can render a distribution
    #: without a second request.
    severity_counts: dict[str, int] = Field(default_factory=dict)
    total_events: int = 0

    def __init__(
        self,
        agent_id: str,
        window_start: datetime,
        window_end: datetime,
        total_alerts: int,
        max_severity: Severity | None = None,
        top_rules: list[RuleCount] | None = None,
        severity_counts: dict[str, int] | None = None,
        total_events: int = 0,
        **data: Any,
    ):
        super().__init__(
            agent_id=agent_id,
            window_start=window_start,
            window_end=window_end,
            total_alerts=total_alerts,
            max_severity=max_severity,
            top_rules=top_rules if top_rules is not None else [],
            severity_counts=severity_counts if severity_counts is not None else {},
            total_events=total_events,
            **data,
        )


class TimelineItem(BaseModel):
    """One entry in an agent's combined event and alert timeline."""

    timestamp: datetime
    kind: Literal["event", "alert"]
    #: `event_id` when kind is `event`, `alert_id` when kind is `alert`.
    reference_id: str
    #: One-line human description: the event type and its salient field, or the
    #: alert summary.
    brief: str
    #: Present only on alerts.
    severity: Severity | None = None
    rule: str | None = None

    def __init__(
        self,
        timestamp: datetime,
        kind: Literal["event", "alert"],
        reference_id: str,
        brief: str,
        severity: Severity | None = None,
        rule: str | None = None,
        **data: Any,
    ):
        super().__init__(
            timestamp=timestamp,
            kind=kind,
            reference_id=reference_id,
            brief=brief,
            severity=severity,
            rule=rule,
            **data,
        )


class HealthResponse(BaseModel):
    """Body of `GET /healthz`."""

    status: str
    database: bool

    def __init__(
        self,
        status: str,
        database: bool,
        **data: Any,
    ):
        super().__init__(
            status=status,
            database=database,
            **data,
        )