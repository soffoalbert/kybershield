"""PostgreSQL connection handling shared by the Python services.

Wraps psycopg's ConnectionPool so services get identical pooling, dict rows,
and transaction semantics. Synchronous by design: the workloads here are
DB-bound batch processing and simple reads, and sync code is markedly easier
to test. The analyser runs its poller in a thread executor so the FastAPI
event loop is never blocked.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection, Cursor
from psycopg.rows import dict_row as dict_row_factory
from psycopg_pool import ConnectionPool

__all__ = ["Database", "dict_row_factory"]

logger = logging.getLogger(__name__)


class Database:
    """A pooled PostgreSQL connection source.

    Usage:
        db = Database(conninfo, min_size=1, max_size=5)
        db.open()
        with db.transaction() as cur:
            cur.execute("SELECT 1")
        db.close()
    """

    def __init__(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int = 5,
        application_name: str = "kybershield",
    ) -> None:
        """Create the pool without connecting.

        Args:
            conninfo: libpq connection string or postgresql:// URL.
            min_size: Connections kept warm.
            max_size: Hard ceiling on concurrent connections.
            application_name: Reported in `pg_stat_activity`, so it is obvious
                which service holds a connection.
        """
        self._pool = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            kwargs={
                # Autocommit by default so a borrowed connection never sits in
                # an implicit open transaction holding locks. `transaction()`
                # opens an explicit block when atomicity is actually wanted.
                "autocommit": True,
                # Set here rather than per cursor so every query in every
                # service returns dicts, which is what the `from_row` mappers
                # expect.
                "row_factory": dict_row_factory,
                "application_name": application_name,
            },
            # Deferred so construction cannot block or raise; `open()` is the
            # explicit, and failable, startup step.
            open=False,
        )

    def open(self, *, wait: bool = True, timeout: float = 30.0) -> None:
        """Open the pool, optionally blocking until the first connection is up.

        Called at service startup. Blocking here means a service that cannot
        reach Postgres fails to start rather than failing every request.

        Raises:
            PoolTimeout: If `wait` is True and no connection is established
                within `timeout` seconds.
        """
        self._pool.open(wait=wait, timeout=timeout)

    def close(self) -> None:
        """Drain and close the pool. Safe to call on an unopened pool."""
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """Borrow a connection from the pool in autocommit-per-statement mode.

        Use for single reads. For anything that must be atomic, use
        :meth:`transaction`.
        """
        with self._pool.connection() as conn:
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[Cursor[dict[str, Any]]]:
        """Borrow a connection and yield a dict-row cursor inside a transaction.

        Commits on clean exit, rolls back on any exception. This is what makes
        "advance the cursor in the same transaction as the alert inserts"
        expressible in one `with` block.
        """
        with self._pool.connection() as conn:
            # Explicit BEGIN/COMMIT, needed because the pool hands out
            # autocommit connections.
            with conn.transaction(), conn.cursor() as cur:
                yield cur

    def healthy(self) -> bool:
        """Return True if a trivial query succeeds.

        Never raises: connection errors are caught and reported as False so
        readiness endpoints can return 503 rather than 500.
        """
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1")
        except Exception:
            logger.warning("database health check failed", exc_info=True)
            return False
        return True
