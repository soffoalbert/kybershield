"""Background analysis loop.

Event-driven with a polling safety net. The `events_notify_ingest` trigger
signals on commit (see :mod:`analyser.notifications`), so a new event is
normally picked up within a round trip instead of waiting out an interval.

The interval is still there, and deliberately so. NOTIFY is not durable: it is
delivered only to sessions listening at commit time, so anything raised while
the analyser is restarting or its connection is broken is lost for good.
`poll_interval_seconds` is the upper bound on how long such an event can sit
unanalysed. Running without a listener at all is still supported and simply
degrades to the original fixed-interval behaviour.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from analyser.engine import AnalysisEngine, RunReport
from analyser.notifications import IngestListener

logger = logging.getLogger(__name__)

#: Bounded so a long outage cannot grow the state object without limit.
RECENT_ERROR_LIMIT = 10

#: Ceiling on the failure backoff, in multiples of the poll interval.
MAX_BACKOFF_MULTIPLIER = 12


@dataclass
class PollerState:
    """Observable poller status, surfaced by `GET /healthz`."""

    running: bool = False
    last_run_at: datetime | None = None
    last_report: RunReport | None = None
    consecutive_failures: int = 0
    total_runs: int = 0
    recent_errors: list[str] = field(default_factory=list)
    #: How many passes were triggered by a notification rather than the
    #: interval. A flat zero in a busy system means the trigger or the listener
    #: is not working and the service has quietly fallen back to polling.
    notify_wakeups: int = 0


class Poller:
    """Owns the background task and its state."""

    def __init__(
        self,
        engine: AnalysisEngine,
        interval_seconds: float,
        state: PollerState | None = None,
        listener: IngestListener | None = None,
    ) -> None:
        """
        Args:
            engine: Pipeline to drive.
            interval_seconds: Fallback poll interval, and the upper bound on
                latency when a notification is missed.
            state: Injectable so the API can hold a reference before start.
            listener: Notification source. Omit to poll on the interval alone.
        """
        self.engine = engine
        self.interval_seconds = interval_seconds
        self.state = state or PollerState()
        self.listener = listener
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the listener and the loop. Idempotent."""
        if self.state.running:
            return
        self.state.running = True
        if self.listener is not None:
            await self.listener.start()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the loop and the listener, and wait for both. Idempotent."""
        if not self.state.running:
            return
        self.state.running = False

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self.listener is not None:
            await self.listener.stop()

    async def _loop(self) -> None:
        """Run passes until cancelled.

        An exception must never escape: a crashed poller would leave the
        service up and apparently healthy while silently analysing nothing.
        Failures are logged, counted, and the loop continues on a backoff so a
        database outage does not become a tight reconnect loop.
        """
        while self.state.running:
            try:
                report = await self.run_pass()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                self.state.consecutive_failures += 1
                self.state.recent_errors.append(str(exc))
                del self.state.recent_errors[:-RECENT_ERROR_LIMIT]
                logger.exception("analysis pass failed")
                await asyncio.sleep(self._backoff_seconds())
                continue

            self.state.last_report = report
            self.state.last_run_at = datetime.now(UTC)
            self.state.total_runs += 1
            self.state.consecutive_failures = 0
            self.state.recent_errors.clear()

            # A full batch means the backlog outlasted this pass, so drain it
            # rather than idling while events are already known to be waiting.
            if report.has_more:
                continue

            await self._wait_for_work()

    async def _wait_for_work(self) -> None:
        """Sleep until notified of new events, or until the interval expires."""
        if self.listener is None:
            await asyncio.sleep(self.interval_seconds)
            return
        if await self.listener.wait(self.interval_seconds):
            self.state.notify_wakeups += 1

    def _backoff_seconds(self) -> float:
        """Exponential backoff on the interval, capped.

        Capped rather than unbounded so the analyser still recovers on its own
        within a predictable time after a long outage.
        """
        multiplier = min(2 ** (self.state.consecutive_failures - 1), MAX_BACKOFF_MULTIPLIER)
        return self.interval_seconds * multiplier

    async def run_pass(self) -> RunReport:
        """Execute one drain in a thread executor.

        The engine is synchronous psycopg. Calling it directly here would block
        the event loop and stall the HTTP endpoints, so it goes through
        `asyncio.to_thread`.
        """
        return await asyncio.to_thread(self.engine.run_once)
