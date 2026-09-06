"""Postgres LISTEN/NOTIFY wakeups for the analyser.

The `events_notify_ingest` trigger (db/migrations/002_notify_on_ingest.sql)
raises a payload-free notification when a transaction commits new events. This
module turns that into an asyncio signal the poller can wait on, which drops
detection latency from the poll interval to roughly a round trip.

The notification carries no data and is treated as advisory. Everything the
analyser actually processes still comes from the cursor drain, so a lost
notification delays a batch until the next fallback poll and a spurious one
costs an empty query. That is the whole reason this is safe: NOTIFY has no
durability, and anything raised while no session is listening is gone.
"""

from __future__ import annotations

import asyncio
import logging

from psycopg import AsyncConnection, sql

logger = logging.getLogger(__name__)


class IngestListener:
    """Holds a dedicated LISTEN connection and signals an asyncio event.

    The connection is deliberately outside :class:`pycommon.Database`'s pool. A
    listening session is long-lived and stateful, so returning it to a pool
    would either hand a `LISTEN`-ing connection to unrelated query code or
    silently drop the subscription.
    """

    def __init__(
        self,
        conninfo: str,
        channel: str,
        reconnect_seconds: float = 5.0,
    ) -> None:
        """
        Args:
            conninfo: libpq connection string for the listener's own session.
            channel: Channel name, matching the trigger's `pg_notify` call.
            reconnect_seconds: Delay before redialling after the connection
                drops.
        """
        self._conninfo = conninfo
        self._channel = channel
        self._reconnect_seconds = reconnect_seconds
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        #: Observable for `GET /healthz`, so a silently dead listener is
        #: visible rather than looking like an idle system.
        self.connected = False

    async def start(self) -> None:
        """Begin listening in a background task. Idempotent."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the listener and wait for the connection to close."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self.connected = False

    async def wait(self, timeout: float) -> bool:
        """Block until a notification arrives or `timeout` elapses.

        The timeout is the fallback poll: it bounds how long a missed
        notification can hide new events.

        @returns True if woken by a notification, False if the timeout fired.
        """
        try:
            await asyncio.wait_for(self._wakeup.wait(), timeout)
        except TimeoutError:
            return False
        # Cleared after the wait, so notifications arriving mid-pass leave the
        # flag set and the next wait returns immediately instead of sleeping
        # through work that is already queued.
        self._wakeup.clear()
        return True

    async def _run(self) -> None:
        """Maintain the subscription, reconnecting until cancelled."""
        while True:
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("listener connection failed; will reconnect")
            finally:
                self.connected = False
            await asyncio.sleep(self._reconnect_seconds)

    async def _listen_once(self) -> None:
        """Connect, subscribe, and forward notifications until the link drops."""
        # autocommit: LISTEN inside a transaction only takes effect on commit.
        async with await AsyncConnection.connect(self._conninfo, autocommit=True) as conn:
            await conn.execute(
                sql.SQL("LISTEN {}").format(sql.Identifier(self._channel))
            )
            self.connected = True
            logger.info("listening on %s", self._channel)

            # Anything committed while the listener was down was never
            # delivered, so treat a fresh subscription as a wakeup.
            self._wakeup.set()

            async for _ in conn.notifies():
                self._wakeup.set()
