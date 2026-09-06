"""Background polling loop.

The analyser's default mode: a loop that wakes every `poll_interval_seconds`
and drains whatever has arrived. Polling rather than push keeps the design free
of a broker, at the cost of a detection latency floor equal to the interval.
The obvious upgrade is Postgres LISTEN/NOTIFY from an ingestion trigger.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from analyser.engine import AnalysisEngine, RunReport


@dataclass
class PollerState:
    """Observable poller status, surfaced by `GET /healthz`."""

    running: bool = False
    last_run_at: datetime | None = None
    last_report: RunReport | None = None
    consecutive_failures: int = 0
    total_runs: int = 0
    recent_errors: list[str] = field(default_factory=list)


class Poller:
    """Owns the background task and its state."""

    def __init__(
        self,
        engine: AnalysisEngine,
        interval_seconds: float,
        state: PollerState | None = None,
    ) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        """Launch the loop as an asyncio task. Idempotent."""
        raise NotImplementedError

    async def stop(self) -> None:
        """Cancel the task and wait for it to unwind. Idempotent."""
        raise NotImplementedError

    async def _loop(self) -> None:
        """Run passes until cancelled.

        Each iteration calls :meth:`run_pass` and then sleeps. An exception
        must never escape: a crashed poller would leave the service up and
        apparently healthy while silently analysing nothing. Failures are
        logged, counted in the state, and the loop continues.

        Backs off up to a ceiling after consecutive failures, so a database
        outage does not turn into a tight reconnect loop.
        """
        raise NotImplementedError

    async def run_pass(self) -> RunReport:
        """Execute one drain in a thread executor.

        The engine is synchronous psycopg. Calling it directly here would block
        the event loop and stall the HTTP endpoints, so it goes through
        `asyncio.to_thread`.
        """
        raise NotImplementedError
