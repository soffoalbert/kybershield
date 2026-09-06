"""IngestListener against real PostgreSQL.

The wakeup path cannot be faked: it depends on the `events_notify_ingest`
trigger firing on commit, on `pg_notify` collapsing repeated signals within one
transaction, and on the notification never being delivered to a session that
was not listening. All three are database behaviour.

Requires `docker compose up -d postgres`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from pycommon import Database

from analyser.notifications import IngestListener
from tests.integration.conftest import seed_event

pytestmark = pytest.mark.integration

#: Matches db/migrations/002_notify_on_ingest.sql.
CHANNEL = "events_ingested"

#: Long enough to cover a round trip on a busy machine, short enough that a
#: genuinely missing notification fails the test rather than hanging it.
WAKEUP_TIMEOUT = 2.0

#: Used where the expected outcome is "no notification", so the test has to
#: wait the timeout out.
QUIET_TIMEOUT = 0.3


@pytest_asyncio.fixture
async def listener(db_url: str) -> AsyncIterator[IngestListener]:
    """A started listener with its subscription already established.

    A fresh subscription sets the wakeup flag by design (anything committed
    while the listener was down was never delivered), so that first wakeup is
    consumed here and each test starts from a quiet listener.
    """
    listener = IngestListener(db_url, CHANNEL, reconnect_seconds=0.1)
    await listener.start()
    assert await listener.wait(WAKEUP_TIMEOUT) is True
    try:
        yield listener
    finally:
        await listener.stop()


class TestWakeup:
    @pytest.mark.asyncio
    async def test_wakes_on_a_committed_event(self, db: Database, listener: IngestListener) -> None:
        """The whole point: detection latency becomes a round trip rather than
        the poll interval."""
        seed_event(db, event_id="evt-notify")

        assert await listener.wait(WAKEUP_TIMEOUT) is True

    @pytest.mark.asyncio
    async def test_reports_the_timeout_when_nothing_is_committed(
        self, listener: IngestListener
    ) -> None:
        """False is what makes the caller's pass a fallback poll rather than a
        notified one."""
        assert await listener.wait(QUIET_TIMEOUT) is False

    @pytest.mark.asyncio
    async def test_a_notification_during_a_pass_is_not_lost(
        self, db: Database, listener: IngestListener
    ) -> None:
        """The flag is cleared after the wait, not before.

        An event committed while the analyser is mid-pass must leave the next
        wait returning immediately, instead of sleeping through work already
        queued.
        """
        seed_event(db, event_id="evt-during-pass")
        assert await listener.wait(WAKEUP_TIMEOUT) is True

        # Nothing new since; the flag was consumed exactly once.
        assert await listener.wait(QUIET_TIMEOUT) is False

    @pytest.mark.asyncio
    async def test_one_wakeup_covers_a_batch_committed_together(
        self, db: Database, db_url: str, listener: IngestListener
    ) -> None:
        """The trigger is FOR EACH STATEMENT with an empty payload, so a
        multi-event insert wakes the analyser once rather than per row."""
        with db.transaction() as cur:
            cur.execute(
                "INSERT INTO agents (agent_id) VALUES ('agent-batch') ON CONFLICT DO NOTHING"
            )
            for index in range(5):
                cur.execute(
                    """
                    INSERT INTO events (event_id, agent_id, occurred_at, type,
                                        payload, raw, client_id)
                    VALUES (%s, 'agent-batch', now(), 'file_read', '{}', '{}', 'test')
                    """,
                    (f"evt-batch-{index}",),
                )

        assert await listener.wait(WAKEUP_TIMEOUT) is True
        assert await listener.wait(QUIET_TIMEOUT) is False

    @pytest.mark.asyncio
    async def test_a_duplicate_submission_raises_no_notification(
        self, db: Database, listener: IngestListener
    ) -> None:
        """`ON CONFLICT DO NOTHING` inserts nothing, so an at-least-once client
        replaying a batch does not wake the analyser."""
        seed_event(db, event_id="evt-once")
        assert await listener.wait(WAKEUP_TIMEOUT) is True

        with db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO events (event_id, agent_id, occurred_at, type,
                                    payload, raw, client_id)
                VALUES ('evt-once', 'agent-alpha', now(), 'file_read', '{}', '{}', 'test')
                ON CONFLICT (event_id) DO NOTHING
                """
            )

        assert await listener.wait(QUIET_TIMEOUT) is False


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_reports_itself_connected_once_subscribed(self, listener: IngestListener) -> None:
        """`GET /healthz` surfaces this, so a silently dead listener is visible
        rather than looking like an idle system."""
        assert listener.connected is True

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, db: Database, db_url: str) -> None:
        listener = IngestListener(db_url, CHANNEL)
        await listener.start()
        await listener.start()
        try:
            assert await listener.wait(WAKEUP_TIMEOUT) is True

            seed_event(db, event_id="evt-idempotent-start")

            # One subscription, so one wakeup rather than two.
            assert await listener.wait(WAKEUP_TIMEOUT) is True
            assert await listener.wait(QUIET_TIMEOUT) is False
        finally:
            await listener.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_the_connection(self, db_url: str) -> None:
        listener = IngestListener(db_url, CHANNEL)
        await listener.start()
        await listener.wait(WAKEUP_TIMEOUT)

        await listener.stop()

        assert listener.connected is False

    @pytest.mark.asyncio
    async def test_stop_is_a_no_op_when_never_started(self, db_url: str) -> None:
        listener = IngestListener(db_url, CHANNEL)

        await listener.stop()

        assert listener.connected is False

    @pytest.mark.asyncio
    async def test_survives_a_connection_it_cannot_open(self) -> None:
        """A database that is not there yet must leave the listener retrying,
        not crash the task that owns it."""
        listener = IngestListener(
            "postgresql://nobody@localhost:1/nothing", CHANNEL, reconnect_seconds=0.05
        )
        await listener.start()
        try:
            assert await listener.wait(QUIET_TIMEOUT) is False
            assert listener.connected is False
        finally:
            await listener.stop()

    @pytest.mark.asyncio
    async def test_a_listener_that_was_down_misses_the_notification(
        self, db: Database, db_url: str
    ) -> None:
        """NOTIFY has no durability, which is why the interval poll stays.

        This is the failure mode `poll_interval_seconds` exists to bound, so it
        is worth pinning rather than leaving as a comment.
        """
        seed_event(db, event_id="evt-while-down")

        listener = IngestListener(db_url, CHANNEL)
        await listener.start()
        try:
            # The subscription itself wakes once, deliberately, to cover
            # exactly this gap.
            assert await listener.wait(WAKEUP_TIMEOUT) is True
            # The event's own notification, though, is gone for good.
            assert await listener.wait(QUIET_TIMEOUT) is False
        finally:
            await listener.stop()
