"""Time window parsing.

Every endpoint accepts `window=24h`, so the parsing lives here rather than
being duplicated at each boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re


def parse_window(window: str) -> timedelta:
    """Parse a shorthand duration such as `30m`, `24h`, or `7d`.

    Accepts an integer followed by one of `m`, `h`, `d`. Case-insensitive.

    Raises:
        ValueError: On an unrecognised suffix, a non-integer quantity, or a
            zero or negative duration.
    """
    if not isinstance(window, str):
        raise ValueError(f"window must be a string, got {type(window)}")
    s = window.strip().lower()
    match = re.fullmatch(r"(\d+)([mhd])", s)
    if not match:
        raise ValueError(f"Invalid window format: {window!r}")
    qty, unit = match.groups()
    try:
        qty = int(qty)
    except Exception:
        raise ValueError(f"Non-integer window quantity: {qty!r}")
    if qty <= 0:
        raise ValueError(f"Window must be positive, got {qty}")
    if unit == "m":
        return timedelta(minutes=qty)
    elif unit == "h":
        return timedelta(hours=qty)
    elif unit == "d":
        return timedelta(days=qty)
    else:
        raise ValueError(f"Unrecognised window unit: {unit!r}")


def _as_utc(dt: datetime) -> datetime:
    # Accept both naive and aware, making naive as UTC aware.
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


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
    passing `2026-08-25T10:00:00` plainly means UTC here.

    Args:
        now: Injectable current time, so window logic is testable without
            freezing the clock globally.

    Returns:
        An inclusive `(start, end)` pair, both timezone-aware.

    Raises:
        ValueError: If `since` is after `until`, or `window` is unparseable.
    """
    if now is None:
        now = datetime.now(timezone.utc)
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
        window_td = parse_window(window)
        start = now - window_td
        if start > now:
            raise ValueError(f"Calculated start ({start}) is after now ({now}) using window={window!r}")
        return (start, now)

    # Default: (now - default_hours, now]
    if default_hours <= 0:
        raise ValueError(f"default_hours must be positive, got {default_hours}")
    start = now - timedelta(hours=default_hours)
    return (start, now)
