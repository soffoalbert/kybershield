"""Response models.

Pydantic rather than the shared dataclasses because these are the public
contract: they generate the OpenAPI schema a teammate would build a dashboard
against. Every list response is wrapped in :class:`Page` so pagination is
uniform and a client never has to guess whether more data exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pycommon import Severity
from pydantic import BaseModel, Field, computed_field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A slice of a larger result set."""

    items: list[T]
    #: Total matching rows ignoring limit/offset, so a UI can size a paginator.
    total: int
    limit: int
    offset: int

    # `computed_field`, not a bare `@property`: pydantic only serialises the
    # latter into the response and the OpenAPI schema when it is declared as a
    # computed field, and this is documented as part of the contract.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_more(self) -> bool:
        """True if rows remain beyond this page."""
        return self.offset + len(self.items) < self.total


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


class RuleCount(BaseModel):
    """A rule and how often it fired within a window."""

    rule: str
    count: int


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


class HealthResponse(BaseModel):
    """Body of `GET /healthz`."""

    status: str
    database: bool
