"""Time window parsing.

Every endpoint accepts `window=24h`, so the parsing lives here rather than
being duplicated at each boundary.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

#: Suffix to the `timedelta` keyword it names. Doubles as the set of units the
#: pattern below accepts, so the two cannot drift apart.
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}

_WINDOW_PATTERN = re.compile(rf"(\d+)([{''.join(_UNITS)}])")


def parse_window(window: str) -> timedelta:
    """Parse a shorthand duration such as `30m`, `24h`, or `7d`.

    Accepts a positive integer followed by one of `m`, `h`, `d`.
    Case-insensitive, and surrounding whitespace is ignored.

    Raises:
        ValueError: On an unrecognised suffix, a non-integer quantity, or a
            zero duration. The pattern makes a negative one unreachable.
    """
    match = _WINDOW_PATTERN.fullmatch(window.strip().lower())
    if not match:
        raise ValueError(f"Invalid window format: {window!r}")

    quantity, unit = match.groups()
    # The pattern guarantees digits, so this cannot raise.
    amount = int(quantity)
    if amount == 0:
        raise ValueError(f"Window must be positive, got {window!r}")
    return timedelta(**{_UNITS[unit]: amount})


def _as_utc(dt: datetime) -> datetime:
    # Accept both naive and aware, making naive as UTC aware.
    if dt.tzinfo is not None:
        return dt.astimezone(UTC)
    return dt.replace(tzinfo=UTC)


def resolve_window(
    since: datetime | None,
    until: datetime | None,
    window: str | None,
    default_hours: int,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve the assorted ways a caller can express a time range.

    Precedence, most explicit first. An explicit bound always beats `window`,
    so passing both `since` and `window` uses `since` and ignores `window`:
    1. Both `since` and `until` given: used verbatim.
    2. `since` only: `(since, now]`.
    3. `window` given: `(now - window, now]`.
    4. Nothing: `(now - default_hours, now]`.

    Naive datetimes are treated as UTC rather than rejected, since a teammate
    passing `2026-08-25T10:00:00` plainly means UTC here.

    Args:
        default_hours: Fallback span. Validated positive by the config, so it
            is not re-checked on every request.
        now: Injectable current time, so window logic is testable without
            freezing the clock globally.

    Returns:
        An inclusive `(start, end)` pair, both timezone-aware.

    Raises:
        ValueError: If `since` is after `until`, or `window` is unparseable.
    """
    if now is None:
        now = datetime.now(UTC)
    else:
        now = _as_utc(now)

    if since is not None:
        since_utc = _as_utc(since)
        if until is not None:
            until_utc = _as_utc(until)
            if since_utc > until_utc:
                raise ValueError(f"`since` ({since_utc}) is after `until` ({until_utc})")
            return (since_utc, until_utc)
        else:
            if since_utc > now:
                raise ValueError(f"`since` ({since_utc}) is after now ({now})")
            return (since_utc, now)

    if window is not None:
        # `parse_window` rejects a zero or negative duration, so the resulting
        # start is always in the past.
        return (now - parse_window(window), now)

    # Default: (now - default_hours, now]
    return (now - timedelta(hours=default_hours), now)
