"""HTTP surface for insights.

Read-only and unauthenticated: operator-facing and bound to the Compose
network. Responses are the `Page` envelope or a flat model, both of which land
in the generated OpenAPI schema at `/docs`, which is the "structured results a
teammate could integrate into a dashboard" the brief asks for.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Query
from pycommon import Severity

from insights.models import AgentSummary, AlertListItem, HealthResponse, Page, TimelineItem
from insights.openapi import APP_METADATA


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the connection pool on startup and close it on shutdown.

    The repository is stored on `app.state` so handlers and tests share it.
    """
    # Assume use of an async database connection pool (e.g., asyncpg)
    # Replace with real repository/database as appropriate.
    from insights.repository import create_repository

    app.state.repository = await create_repository()
    try:
        yield
    finally:
        await app.state.repository.aclose()

def create_app() -> FastAPI:
    """Build the FastAPI application."""
    from fastapi import HTTPException, status
    from fastapi.responses import JSONResponse
    from typing import List, Optional
    from insights.repository import get_repository
    from insights.models import (
        Page,
        AlertListItem,
        AgentSummary,
        HealthResponse,
        TimelineItem,
    )
    from pydantic import ValidationError

    app = FastAPI(lifespan=lifespan, **APP_METADATA)

    # Constants
    default_window_hours = 24
    max_page_size = 500

    # Helper to parse time filter queries
    def parse_time_params(
        since: Optional[datetime],
        until: Optional[datetime],
        window: Optional[str],
        default_hours: int = default_window_hours,
    ):
        import re
        from datetime import timedelta

        now = datetime.utcnow()
        if since and until:
            if until < since:
                raise HTTPException(
                    status_code=400, detail="until must be after since"
                )
            return since, until

        if window:
            # Parse window string like "24h" or "7d"
            m = re.match(r"^(\d+)([hd])$", window)
            if not m:
                raise HTTPException(
                    status_code=400, detail="Invalid window parameter"
                )
            val, units = m.groups()
            try:
                val = int(val)
            except Exception:
                raise HTTPException(
                    status_code=400, detail="Invalid window value"
                )
            if units == "h":
                delta = timedelta(hours=val)
            elif units == "d":
                delta = timedelta(days=val)
            else:
                raise HTTPException(
                    status_code=400, detail="Invalid window units"
                )
            end = until or now
            start = end - delta
            if start > end:
                raise HTTPException(
                    status_code=400, detail="Window results in inverted range"
                )
            return start, end

        # Default: last 24h or as per default_hours
        end = until or now
        start = since or (end - timedelta(hours=default_hours))
        if start > end:
            raise HTTPException(
                status_code=400, detail="Time range is inverted"
            )
        return start, end

    @app.get(
        "/v1/alerts",
        tags=["alerts"],
        summary="List alerts (paged, newest first)",
        response_model=Page[AlertListItem],
    )
    async def list_alerts(
        since: Optional[datetime] = Query(
            None, description="Start of the time window (RFC3339)"
        ),
        until: Optional[datetime] = Query(
            None, description="End of the time window (RFC3339)"
        ),
        window: Optional[str] = Query(
            None,
            description="Window ending at 'until' (e.g., '24h', '7d'). Takes precedence if set.",
        ),
        agent_id: Optional[str] = Query(
            None, description="Filter to specific agent id"
        ),
        rule: Optional[str] = Query(
            None, description="Filter by rule name"
        ),
        severity_min: Optional[Severity] = Query(
            None, description="Minimum severity"
        ),
        limit: int = Query(
            100, ge=1, le=max_page_size * 10, description="Max results per page"
        ),
        offset: int = Query(
            0, ge=0, description="Zero-based offset for pagination"
        ),
    ) -> Page[AlertListItem]:
        repo = get_repository(app)
        start, end = parse_time_params(since, until, window)
        # Clamp limit to max_page_size
        real_limit = min(limit, max_page_size)
        results, total = await repo.list_alerts(
            since=start,
            until=end,
            agent_id=agent_id,
            rule=rule,
            severity_min=severity_min,
            limit=real_limit,
            offset=offset,
        )
        return Page[AlertListItem](
            total=total,
            limit=real_limit,
            offset=offset,
            items=results,
        )

    @app.get(
        "/v1/agents/{agent_id}/summary",
        tags=["agents"],
        summary="Summary for a single agent in a window",
        response_model=AgentSummary,
    )
    async def agent_summary(
        agent_id: str,
        since: Optional[datetime] = Query(
            None, description="Start of time window (RFC3339)"
        ),
        until: Optional[datetime] = Query(
            None, description="End of time window (RFC3339)"
        ),
        window: Optional[str] = Query(
            None,
            description="Window ending at 'until' (e.g., '24h'). Takes precedence if set.",
        ),
    ) -> AgentSummary:
        repo = get_repository(app)
        start, end = parse_time_params(since, until, window)
        summary = await repo.agent_summary(agent_id, since=start, until=end)
        if summary is None:
            # Return zeroed summary if no alerts for this agent
            return AgentSummary(agent_id=agent_id)
        return summary

    @app.get(
        "/v1/agents/{agent_id}/timeline",
        tags=["agents"],
        summary="Alerts/events timeline for a single agent",
        response_model=List[TimelineItem],
    )
    async def agent_timeline(
        agent_id: str,
        since: Optional[datetime] = Query(
            None, description="Start of time window (RFC3339)"
        ),
        until: Optional[datetime] = Query(
            None, description="End of time window (RFC3339)"
        ),
        window: Optional[str] = Query(
            None,
            description="Time window duration ending at 'until'.",
        ),
        limit: int = Query(
            100, ge=1, le=max_page_size * 10, description="Max timeline items"
        ),
    ) -> List[TimelineItem]:
        repo = get_repository(app)
        start, end = parse_time_params(since, until, window)
        real_limit = min(limit, max_page_size)
        timeline = await repo.agent_timeline(
            agent_id, since=start, until=end, limit=real_limit
        )
        return timeline

    @app.get(
        "/healthz",
        tags=["health"],
        summary="Readiness/liveness probe for the database",
        response_model=HealthResponse,
    )
    async def healthz() -> HealthResponse:
        repo = get_repository(app)
        try:
            ok = await repo.is_healthy()
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=HealthResponse(ok=False, detail="db unreachable").dict(),
            )
        return HealthResponse(ok=ok, detail=None if ok else "db unhealthy")

    return app


app = create_app()
