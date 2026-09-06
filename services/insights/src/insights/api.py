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
    raise NotImplementedError


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Construct with ``FastAPI(lifespan=lifespan, **APP_METADATA)``. That gives
    interactive Swagger UI at ``/docs`` and ReDoc at ``/redoc`` for free, with
    the prose and tag groups defined in :mod:`insights.openapi`.

    Give every route a ``tags=[...]``, a ``summary=``, and a
    ``response_model=`` from :mod:`insights.models`; the response model is what
    turns the generated document into something a dashboard client can be
    generated from. Declare query parameters with ``Query(..., description=)``
    so the filters are self-documenting in the UI.

    Routes:
        GET /v1/alerts
            Query: since, until, window, agent_id, rule, severity_min, limit,
            offset. Defaults to the last `default_window_hours`.
            Returns `Page[AlertListItem]` ordered newest first.
            400 on an unparseable window or an inverted range.

        GET /v1/agents/{agent_id}/summary
            Query: since, until, window (default 24h).
            Returns `AgentSummary`. An agent with no alerts returns a zeroed
            summary rather than a 404.

        GET /v1/agents/{agent_id}/timeline
            Query: since, until, window, limit.
            Returns `list[TimelineItem]` merging events and alerts.

        GET /healthz
            Returns `HealthResponse`; 503 when the database is unreachable.

    `limit` is clamped to `max_page_size` rather than rejected, so a client
    asking for too much gets data instead of an error.
    """
    raise NotImplementedError


app = create_app()
