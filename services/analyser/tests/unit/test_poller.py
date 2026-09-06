"""The background analysis loop.

The loop must never let an exception escape: a crashed poller leaves the
service up and apparently healthy while silently analysing nothing. Most of
these tests are about that guarantee and about the state `GET /healthz`
reports.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import pytest

from analyser.engine import RunReport
from analyser.poller import MAX_BACKOFF_MULTIPLIER, RECENT_ERROR_LIMIT, Poller, PollerState

#: Long enough that a pass is measurable, short enough not to slow the suite.
BLOCKING_MS = 0.05


class FakeEngine:
    """Engine whose passes the test scripts.

    `run_once` is synchronous, as the real one is, because the poller putting
    it on a thread is part of what these tests check.
    """

    def __init__(
        self,
        *,
        fail_times: int = 0,
        has_more: bool = False,
        blocking_seconds: float = 0.0,
    ) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.has_more = has_more
        self.blocking_seconds = blocking_seconds

    def run_once(self) -> RunReport:
        self.calls += 1
        if self.blocking_seconds:
            time.sleep(self.blocking_seconds)
        if self.calls <= self.fail_times:
            raise RuntimeError(f"pass {self.calls} failed")
        return RunReport(events_examined=1, batch_full=self.has_more)


class FakeListener:
    """IngestListener stand-in whose wakeups the test controls."""

    def __init__(self, *, notified: bool = True) -> None:
        self.notified = notified
        self.started = 0
        self.stopped = 0
        self.waits = 0
        self.connected = False

    async def start(self) -> None:
        self.started += 1
        self.connected = True

    async def stop(self) -> None:
        self.stopped += 1
        self.connected = False

    async def wait(self, timeout: float) -> bool:
        self.waits += 1
        # Yield, so a loop waiting on this cannot starve the event loop.
        await asyncio.sleep(0)
        return self.notified


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll `predicate` until it holds, failing the test on timeout.

    The loop runs as a task, so a test cannot simply await it; this is how an
    assertion waits for the loop to reach a state without a fixed sleep.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached within the timeout")


async def run_briefly(poller: Poller, until: Callable[[], bool]) -> None:
    """Start the poller, wait for `until`, then stop it again."""
    await poller.start()
    try:
        await wait_until(until)
    finally:
        await poller.stop()


class TestRunPass:
    @pytest.mark.asyncio
    async def test_returns_the_engines_report(self) -> None:
        poller = Poller(FakeEngine(), interval_seconds=0)

        report = await poller.run_pass()

        assert report.events_examined == 1

    @pytest.mark.asyncio
    async def test_does_not_block_the_event_loop(self) -> None:
        """The reason the synchronous engine runs in a thread executor.

        Calling it inline would stall every HTTP handler for the duration of a
        pass, which is what `asyncio.to_thread` exists to prevent here.
        """
        poller = Poller(FakeEngine(blocking_seconds=BLOCKING_MS), interval_seconds=0)
        ticks = 0

        async def tick() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0)

        ticker = asyncio.create_task(tick())
        await poller.run_pass()
        ticker.cancel()

        assert ticks > 1


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_marks_the_poller_running_and_starts_the_listener(self) -> None:
        listener = FakeListener()
        poller = Poller(FakeEngine(), interval_seconds=0, listener=listener)

        await poller.start()
        try:
            assert poller.state.running is True
            assert listener.started == 1
        finally:
            await poller.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        listener = FakeListener()
        poller = Poller(FakeEngine(), interval_seconds=0, listener=listener)

        await poller.start()
        await poller.start()
        try:
            assert listener.started == 1
        finally:
            await poller.stop()

    @pytest.mark.asyncio
    async def test_stop_halts_the_loop_and_the_listener(self) -> None:
        engine = FakeEngine()
        listener = FakeListener()
        poller = Poller(engine, interval_seconds=0, listener=listener)

        await run_briefly(poller, lambda: engine.calls > 0)

        assert poller.state.running is False
        assert listener.stopped == 1
        # No further passes once stopped.
        calls_at_stop = engine.calls
        await asyncio.sleep(0.02)
        assert engine.calls == calls_at_stop

    @pytest.mark.asyncio
    async def test_stop_is_a_no_op_when_never_started(self) -> None:
        """Covers the `poller_enabled=false` teardown path in the API lifespan."""
        listener = FakeListener()
        poller = Poller(FakeEngine(), interval_seconds=0, listener=listener)

        await poller.stop()

        assert poller.state.running is False
        assert listener.stopped == 0

    @pytest.mark.asyncio
    async def test_accepts_an_injected_state(self) -> None:
        """The API holds a reference to the state before the poller starts."""
        state = PollerState()
        poller = Poller(FakeEngine(), interval_seconds=0, state=state)

        assert poller.state is state


class TestLoop:
    @pytest.mark.asyncio
    async def test_runs_passes_until_stopped(self) -> None:
        engine = FakeEngine()
        poller = Poller(engine, interval_seconds=0)

        await run_briefly(poller, lambda: poller.state.total_runs >= 3)

        assert engine.calls >= 3

    @pytest.mark.asyncio
    async def test_records_the_last_report_and_run_time(self) -> None:
        poller = Poller(FakeEngine(), interval_seconds=0)

        await run_briefly(poller, lambda: poller.state.total_runs >= 1)

        assert poller.state.last_run_at is not None
        assert poller.state.last_report is not None
        assert poller.state.last_report.events_examined == 1

    @pytest.mark.asyncio
    async def test_survives_a_failing_pass(self) -> None:
        """A database outage must not kill the loop."""
        engine = FakeEngine(fail_times=1)
        poller = Poller(engine, interval_seconds=0)

        await run_briefly(poller, lambda: poller.state.total_runs >= 1)

        assert engine.calls >= 2
        assert poller.state.running is False

    @pytest.mark.asyncio
    async def test_counts_and_records_consecutive_failures(self) -> None:
        engine = FakeEngine(fail_times=100)
        poller = Poller(engine, interval_seconds=0)

        await run_briefly(poller, lambda: poller.state.consecutive_failures >= 2)

        assert poller.state.recent_errors
        assert "failed" in poller.state.recent_errors[-1]

    @pytest.mark.asyncio
    async def test_bounds_the_recorded_errors(self) -> None:
        """A long outage must not grow the state object without limit."""
        engine = FakeEngine(fail_times=1000)
        poller = Poller(engine, interval_seconds=0)

        await run_briefly(
            poller, lambda: poller.state.consecutive_failures > RECENT_ERROR_LIMIT + 2
        )

        assert len(poller.state.recent_errors) == RECENT_ERROR_LIMIT

    @pytest.mark.asyncio
    async def test_clears_the_failure_state_after_a_good_pass(self) -> None:
        engine = FakeEngine(fail_times=2)
        poller = Poller(engine, interval_seconds=0)

        await run_briefly(poller, lambda: poller.state.total_runs >= 1)

        assert poller.state.consecutive_failures == 0
        assert poller.state.recent_errors == []

    @pytest.mark.asyncio
    async def test_drains_without_waiting_while_the_batch_is_full(self) -> None:
        """A full batch means work is already known to be waiting."""
        listener = FakeListener()
        poller = Poller(FakeEngine(has_more=True), interval_seconds=0, listener=listener)

        await run_briefly(poller, lambda: poller.state.total_runs >= 3)

        # Straight back to the next pass, so the listener is never consulted.
        assert listener.waits == 0

    @pytest.mark.asyncio
    async def test_counts_wakeups_triggered_by_a_notification(self) -> None:
        listener = FakeListener(notified=True)
        poller = Poller(FakeEngine(), interval_seconds=0, listener=listener)

        await run_briefly(poller, lambda: poller.state.notify_wakeups >= 2)

        assert poller.state.notify_wakeups >= 2

    @pytest.mark.asyncio
    async def test_does_not_count_a_wakeup_from_the_fallback_interval(self) -> None:
        """A flat zero here is the signal that the trigger is not working."""
        listener = FakeListener(notified=False)
        poller = Poller(FakeEngine(), interval_seconds=0, listener=listener)

        await run_briefly(poller, lambda: listener.waits >= 2)

        assert poller.state.notify_wakeups == 0

    @pytest.mark.asyncio
    async def test_polls_on_the_interval_when_there_is_no_listener(self) -> None:
        """Running without a listener degrades to fixed-interval polling."""
        engine = FakeEngine()
        poller = Poller(engine, interval_seconds=0, listener=None)

        await run_briefly(poller, lambda: engine.calls >= 2)

        assert poller.state.notify_wakeups == 0


class TestBackoff:
    @pytest.mark.parametrize(
        ("failures", "expected_multiplier"),
        [(1, 1), (2, 2), (3, 4), (4, 8), (5, MAX_BACKOFF_MULTIPLIER)],
    )
    def test_backs_off_exponentially_up_to_the_cap(
        self, failures: int, expected_multiplier: int
    ) -> None:
        """Capped so the analyser still recovers on its own within a
        predictable time after a long outage."""
        poller = Poller(
            FakeEngine(),
            interval_seconds=2.0,
            state=PollerState(consecutive_failures=failures),
        )

        assert poller._backoff_seconds() == 2.0 * expected_multiplier

    def test_stays_capped_however_long_the_outage_lasts(self) -> None:
        poller = Poller(
            FakeEngine(), interval_seconds=1.0, state=PollerState(consecutive_failures=50)
        )

        assert poller._backoff_seconds() == 1.0 * MAX_BACKOFF_MULTIPLIER
