"""Time window parsing.

Both the HTTP API and the CLI accept `window=24h`, so the parsing lives here
rather than being duplicated at each boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def parse_window(window: str) -> timedelta:
    """Parse a shorthand duration such as `30m`, `24h`, or `7d`.

    Accepts an integer followed by one of `m`, `h`, `d`. Case-insensitive.

    Raises:
        ValueError: On an unrecognised suffix, a non-integer quantity, or a
            zero or negative duration.
    """
    raise NotImplementedError


def resolve_window(
    since: datetime | None,
    until: datetime | None,
    window: str | None,
    default_hours: int,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve the assorted ways a caller can express a time range.

    Precedence, most explicit first:
    1. Both `since` and `until` given: used verbatim.
    2. `window` given: `(now - window, now]`.
    3. `since` only: `(since, now]`.
    4. Nothing: `(now - default_hours, now]`.

    Naive datetimes are treated as UTC rather than rejected, since a teammate
    passing `2026-08-25T10:00:00` on the CLI plainly means UTC here.

    Args:
        now: Injectable current time, so window logic is testable without
            freezing the clock globally.

    Returns:
        An inclusive `(start, end)` pair, both timezone-aware.

    Raises:
        ValueError: If `since` is after `until`, or `window` is unparseable.
    """
    raise NotImplementedError
