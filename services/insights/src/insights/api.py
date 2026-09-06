"""HTTP surface for insights.

Read-only and unauthenticated: operator-facing and bound to the Compose
network. Responses are the `Page` envelope or a flat model, both of which land
in the generated OpenAPI schema at `/docs`, which is the "structured results a
teammate could integrate into a dashboard" the brief asks for.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request, Response
from pycommon import Database, Severity

from insights.config import InsightsConfig, get_config
from insights.models import AgentSummary, AlertListItem, HealthResponse, Page, TimelineItem
from insights.openapi import APP_METADATA
from insights.repository import PgInsightsRepository
from insights.windows import resolve_window


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the connection pool on startup and close it on shutdown.

    The config and repository are stored on `app.state` so handlers and tests
    share them. `Database.open` blocks: a service that cannot reach Postgres
    should fail to start rather than accept traffic and fail every request.
    """
    config = get_config()

    db = Database(
        config.database_url,
        min_size=config.db_pool_min_size,
        max_size=config.db_pool_max_size,
        application_name="kybershield-insights",
    )
    db.open()

    app.state.config = config
    app.state.db = db
    app.state.repository = PgInsightsRepository(db)

    try:
        yield
    finally:
        db.close()


def _window(
    config: InsightsConfig,
    since: datetime | None,
    until: datetime | None,
    window: str | None,
) -> tuple[datetime, datetime]:
    """Resolve the request's time bounds, answering 400 on a bad range.

    `resolve_window` raises `ValueError` for an unparseable `window` or an
    inverted range, both of which are the caller's mistake rather than ours.
    """
    try:
        return resolve_window(since, until, window, config.default_window_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Swagger UI is at ``/docs`` and ReDoc at ``/redoc``, with the prose and tag
    groups from :mod:`insights.openapi`.

    Every handler goes through `asyncio.to_thread`: the repository and pool are
    synchronous psycopg, so calling them inline would block the event loop and
    stall every other request.
    """
    app = FastAPI(lifespan=lifespan, **APP_METADATA)

    @app.get(
        "/v1/alerts",
        tags=["alerts"],
        summary="List alerts (paged, newest first)",
        response_model=Page[AlertListItem],
    )
    async def list_alerts(
        request: Request,
        since: datetime | None = Query(None, description="Start of the window (ISO-8601)"),
        until: datetime | None = Query(None, description="End of the window (ISO-8601)"),
        window: str | None = Query(None, description="Window shorthand, e.g. 30m, 24h, 7d"),
        agent_id: str | None = Query(None, description="Filter to one agent"),
        rule: str | None = Query(None, description="Filter to one rule id"),
        severity_min: Severity | None = Query(None, description="Minimum severity, inclusive"),
        limit: int | None = Query(None, ge=1, description="Rows per page"),
        offset: int = Query(0, ge=0, description="Rows to skip"),
    ) -> Page[AlertListItem]:
        """One page of alerts, newest first.

        `limit` is clamped to `MAX_PAGE_SIZE` rather than rejected, so an
        over-eager client gets data instead of an error.
        """
        config: InsightsConfig = request.app.state.config
        repo: PgInsightsRepository = request.app.state.repository

        start, end = _window(config, since, until, window)
        page_size = min(limit or config.default_page_size, config.max_page_size)

        items, total = await asyncio.to_thread(
            repo.list_alerts,
            since=start,
            until=end,
            agent_id=agent_id,
            rule=rule,
            severity_min=severity_min,
            limit=page_size,
            offset=offset,
        )
        return Page[AlertListItem](items=items, total=total, limit=page_size, offset=offset)

    @app.get(
        "/v1/agents/{agent_id}/summary",
        tags=["agents"],
        summary="Risk posture for one agent over a window",
        response_model=AgentSummary,
    )
    async def agent_summary(
        request: Request,
        agent_id: str,
        since: datetime | None = Query(None, description="Start of the window (ISO-8601)"),
        until: datetime | None = Query(None, description="End of the window (ISO-8601)"),
        window: str | None = Query(None, description="Window shorthand, e.g. 30m, 24h, 7d"),
    ) -> AgentSummary:
        """Totals, peak severity, and top rules for one agent.

        An unknown or quiet agent returns a zeroed summary with `200`, not a
        `404`: the question was well-formed and the answer is "nothing".
        """
        config: InsightsConfig = request.app.state.config
        repo: PgInsightsRepository = request.app.state.repository

        start, end = _window(config, since, until, window)
        return await asyncio.to_thread(
            repo.agent_summary,
            agent_id,
            start,
            end,
            config.top_rules_limit,
        )

    @app.get(
        "/v1/agents/{agent_id}/timeline",
        tags=["agents"],
        summary="One agent's events and alerts merged in time order",
        response_model=Page[TimelineItem],
    )
    async def agent_timeline(
        request: Request,
        agent_id: str,
        since: datetime | None = Query(None, description="Start of the window (ISO-8601)"),
        until: datetime | None = Query(None, description="End of the window (ISO-8601)"),
        window: str | None = Query(None, description="Window shorthand, e.g. 30m, 24h, 7d"),
        limit: int | None = Query(None, ge=1, description="Maximum entries"),
    ) -> Page[TimelineItem]:
        """Events and alerts interleaved, newest first."""
        config: InsightsConfig = request.app.state.config
        repo: PgInsightsRepository = request.app.state.repository

        start, end = _window(config, since, until, window)
        page_size = min(limit or config.default_page_size, config.max_page_size)

        items = await asyncio.to_thread(repo.agent_timeline, agent_id, start, end, page_size)
        return Page[TimelineItem](
            items=items, total=len(items), limit=page_size, offset=0
        )

    @app.get(
        "/healthz",
        tags=["health"],
        summary="Liveness and database reachability",
        response_model=HealthResponse,
    )
    async def healthz(request: Request, response: Response) -> HealthResponse:
        """Report health, answering 503 when the database is unreachable.

        `Database.healthy` never raises, so an outage shows up as a structured
        503 rather than a 500 with a stack trace.
        """
        repo: PgInsightsRepository = request.app.state.repository

        database = await asyncio.to_thread(repo.healthy)
        if not database:
            response.status_code = 503

        return HealthResponse(status="ok" if database else "degraded", database=database)

    return app


app = create_app()
