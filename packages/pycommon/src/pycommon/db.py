"""PostgreSQL connection handling shared by the Python services.

Wraps psycopg's ConnectionPool so services get identical pooling, dict rows,
and transaction semantics. Synchronous by design: the workloads here are
DB-bound batch processing and simple reads, and sync code is markedly easier
to test. The analyser runs its poller in a thread executor so the FastAPI
event loop is never blocked.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection, Cursor
from psycopg.rows import dict_row as dict_row_factory

__all__ = ["Database", "dict_row_factory"]


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
        raise NotImplementedError

    def open(self, *, wait: bool = True, timeout: float = 30.0) -> None:
        """Open the pool, optionally blocking until the first connection is up.

        Called at service startup. Blocking here means a service that cannot
        reach Postgres fails to start rather than failing every request.

        Raises:
            PoolTimeout: If `wait` is True and no connection is established
                within `timeout` seconds.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Drain and close the pool. Safe to call on an unopened pool."""
        raise NotImplementedError

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """Borrow a connection from the pool in autocommit-per-statement mode.

        Use for single reads. For anything that must be atomic, use
        :meth:`transaction`.
        """
        raise NotImplementedError

    @contextmanager
    def transaction(self) -> Iterator[Cursor[dict[str, Any]]]:
        """Borrow a connection and yield a dict-row cursor inside a transaction.

        Commits on clean exit, rolls back on any exception. This is what makes
        "advance the cursor in the same transaction as the alert inserts"
        expressible in one `with` block.
        """
        raise NotImplementedError

    def healthy(self) -> bool:
        """Return True if a trivial query succeeds.

        Never raises: connection errors are caught and reported as False so
        readiness endpoints can return 503 rather than 500.
        """
        raise NotImplementedError
