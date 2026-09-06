"""HTTP surface for the analyser.

Mostly operational: the poller does the work, and these endpoints exist so a
reviewer can force a pass and inspect what the rules are configured to do
without waiting on the interval. Unauthenticated, since the service is bound to
the Compose network and is operator-facing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from pycommon import Database, configure_logging, install_error_handlers
from pydantic import BaseModel

from analyser.config import AnalyserConfig, get_config, rule_config
from analyser.engine import AnalysisEngine, RunReport
from analyser.notifications import IngestListener
from analyser.openapi import APP_METADATA
from analyser.poller import Poller
from analyser.repository import PgAnalysisRepository
from analyser.rules import default_rules

logger = logging.getLogger(__name__)


class RunResponse(BaseModel):
    """Result of a manual analysis pass."""

    events_examined: int
    alerts_generated: int
    alerts_written: int
    cursor_before: int
    cursor_after: int
    duration_ms: float
    rule_failures: list[str]

    @classmethod
    def from_report(cls, report: RunReport) -> RunResponse:
        """Project the engine's report onto the wire shape.

        Explicit rather than `asdict`, so an internal field added to
        :class:`RunReport` does not silently become part of the API.
        """
        return cls(
            events_examined=report.events_examined,
            alerts_generated=report.alerts_generated,
            alerts_written=report.alerts_written,
            cursor_before=report.cursor_before,
            cursor_after=report.cursor_after,
            duration_ms=report.duration_ms,
            rule_failures=report.rule_failures,
        )


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
    #: False while the LISTEN connection is down, which means the service has
    #: silently degraded to interval polling.
    listener_connected: bool
    #: Passes triggered by a notification rather than the fallback interval. A
    #: flat zero on a busy system points at the trigger or the listener.
    notify_wakeups: int


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the pool, build the engine, start the poller; tear down in reverse.

    Everything is stashed on `app.state` so route handlers and tests reach the
    same instances. When `poller_enabled` is false the poller is skipped, which
    is how integration tests get a deterministic pipeline driven only by
    explicit `run_once` calls.

    The listener opens its own connection rather than borrowing from the pool,
    so the pool is sized without counting it.
    """
    config = get_config()
    configure_logging(config.log_level)

    db = Database(
        config.psycopg_conninfo,
        min_size=config.db_pool_min_size,
        max_size=config.db_pool_max_size,
        application_name="kybershield-analyser",
    )
    # Blocking: a service that cannot reach Postgres should fail to start
    # rather than accept traffic and fail every request.
    db.open()

    engine = AnalysisEngine(
        default_rules(),
        PgAnalysisRepository(db),
        config,
        batch_size=config.batch_size,
    )

    listener = (
        IngestListener(
            config.psycopg_conninfo,
            config.notify_channel,
            config.listen_reconnect_seconds,
        )
        if config.listen_enabled
        else None
    )
    poller = Poller(engine, config.poll_interval_seconds, listener=listener)

    app.state.config = config
    app.state.db = db
    app.state.engine = engine
    app.state.poller = poller

    if config.poller_enabled:
        await poller.start()

    try:
        yield
    finally:
        # `Poller.stop` also stops the listener, and is a no-op when the poller
        # was never started, so this covers the poller_enabled=False case too.
        await poller.stop()
        db.close()


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Swagger UI is at ``/docs`` and ReDoc at ``/redoc``, with the prose and tag
    groups from :mod:`analyser.openapi`.

    Every handler that touches the database goes through `asyncio.to_thread`:
    the engine and pool are synchronous psycopg, so calling them inline would
    block the event loop and stall every other request.
    """
    app = FastAPI(lifespan=lifespan, **APP_METADATA)
    # Same `{error, issues}` envelope the ingestion service returns, so a
    # client parses one error shape across all three.
    install_error_handlers(app)

    @app.post(
        "/v1/analyze/run",
        tags=["analysis"],
        summary="Run one analysis pass now",
        response_model=RunResponse,
    )
    async def analyze_run(request: Request, drain: bool = False) -> RunResponse:
        """Force a pass without waiting for a notification or the interval.

        With `drain=true`, keeps claiming batches until the backlog is empty,
        which is what a reviewer wants right after seeding demo data.
        """
        engine: AnalysisEngine = request.app.state.engine
        runner = engine.run_until_caught_up if drain else engine.run_once
        return RunResponse.from_report(await asyncio.to_thread(runner))

    @app.post(
        "/v1/analyze/backfill",
        tags=["analysis"],
        summary="Re-run every rule over historical events",
        response_model=RunResponse,
    )
    async def analyze_backfill(request: Request, body: BackfillRequest) -> RunResponse:
        """Re-analyse history without moving the live cursor.

        Safe to repeat: the `(event_id, rule)` unique constraint skips findings
        already recorded, so only genuinely new detections are written.
        """
        engine: AnalysisEngine = request.app.state.engine
        report = await asyncio.to_thread(engine.backfill, body.since)
        return RunResponse.from_report(report)

    @app.get(
        "/v1/rules",
        tags=["rules"],
        summary="List registered detections and their live thresholds",
        response_model=list[RuleInfo],
    )
    async def list_rules(request: Request) -> list[RuleInfo]:
        """Report what the analyser is actually configured to detect."""
        config: AnalyserConfig = request.app.state.config
        engine: AnalysisEngine = request.app.state.engine
        return [
            RuleInfo(id=rule.id, description=rule.description, config=rule_config(rule.id, config))
            for rule in engine.rules
        ]

    @app.get(
        "/healthz",
        tags=["health"],
        summary="Liveness, database reachability, and poller state",
        response_model=HealthResponse,
    )
    async def healthz(request: Request, response: Response) -> HealthResponse:
        """Report health, answering 503 when the database is unreachable.

        `Database.healthy` never raises, so an outage shows up as a structured
        503 rather than a 500 with a stack trace.
        """
        db: Database = request.app.state.db
        poller: Poller = request.app.state.poller

        database = await asyncio.to_thread(db.healthy)
        if not database:
            response.status_code = 503

        return HealthResponse(
            status="ok" if database else "degraded",
            database=database,
            poller_running=poller.state.running,
            last_run_at=poller.state.last_run_at,
            consecutive_failures=poller.state.consecutive_failures,
            listener_connected=poller.listener.connected if poller.listener else False,
            notify_wakeups=poller.state.notify_wakeups,
        )

    return app


app = create_app()
