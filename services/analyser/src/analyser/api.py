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
    raise NotImplementedError


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Routes:
        POST /v1/analyze/run       Drain the backlog now, return a RunResponse.
        POST /v1/analyze/backfill  Re-run rules over history, return a RunResponse.
        GET  /v1/rules             List registered rules and their config.
        GET  /healthz              Liveness, database reachability, poller state.
    """
    raise NotImplementedError


app = create_app()
