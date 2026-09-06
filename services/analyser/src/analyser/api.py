"""HTTP surface for the analyser.

Mostly operational: the poller does the work, and these endpoints exist so a
reviewer can force a pass and inspect what the rules are configured to do
without waiting on the interval. Unauthenticated, since the service is bound to
the Compose network and is operator-facing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from analyser.openapi import APP_METADATA


class RunResponse(BaseModel):
    """Result of a manual analysis pass."""

    events_examined: int
    alerts_generated: int
    alerts_written: int
    cursor_before: int
    cursor_after: int
    duration_ms: float
    rule_failures: list[str]


class BackfillRequest(BaseModel):
    """Body for `POST /v1/analyze/backfill`."""

    #: Only re-analyse events at or after this instant. Omit for all history.
    since: datetime | None = None


class RuleInfo(BaseModel):
    """One entry in `GET /v1/rules`."""

    id: str
    description: str
    #: The rule's effective configuration, so a reviewer can see the live
    #: thresholds without reading the environment.
    config: dict[str, Any]


class HealthResponse(BaseModel):
    """Body of `GET /healthz`."""

    status: str
    database: bool
    poller_running: bool
    last_run_at: datetime | None
    consecutive_failures: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the pool, build the engine, start the poller; tear down in reverse.

    Everything is stashed on `app.state` so route handlers and tests reach the
    same instances. When `poller_enabled` is false the poller is skipped, which
    is how integration tests get a deterministic pipeline driven only by
    explicit `run_once` calls.
    """

    config = get_config()
    engine = AnalysisEngine(rules, repo, config, batch_size=config.batch_size)
    app.state.engine = engine
    app.state.poller = Poller(engine, config.poll_interval_seconds)
    app.state.poller.start()

    yield

    app.state.poller.stop()
    app.state.engine.shutdown()
    app.state.pool.close()


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Construct with ``FastAPI(lifespan=lifespan, **APP_METADATA)``. That gives
    interactive Swagger UI at ``/docs`` and ReDoc at ``/redoc`` for free, with
    the prose and tag groups defined in :mod:`analyser.openapi`.

    Give every route a ``tags=[...]``, a ``summary=``, and a ``response_model=``
    so the generated document is navigable rather than a flat list of paths.

    Routes:
        POST /v1/analyze/run       tags=["analysis"] -> RunResponse
        POST /v1/analyze/backfill  tags=["analysis"] -> RunResponse
        GET  /v1/rules             tags=["rules"]    -> list[RuleInfo]
        GET  /healthz              tags=["health"]   -> HealthResponse
    """
    return FastAPI(lifespan=lifespan, **APP_METADATA)
    rules = get_rules()
    repo = PgAnalysisRepository(db)
    config = get_config()
    engine = AnalysisEngine(rules, repo, config, batch_size=config.batch_size)
    app.state.engine = engine
    app.state.poller = Poller(engine, config.poll_interval_seconds)
    app.state.poller.start()

    yield

    app.state.poller.stop()
    app.state.engine.shutdown()
    app.state.pool.close()

app = create_app()
