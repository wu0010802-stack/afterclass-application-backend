"""Shared helpers for the services / routes layers."""

from datetime import datetime, timedelta, timezone

# Taiwan timezone (UTC+8). The Postgres server stores timestamps naive-UTC,
# so anything we hand back to the frontend needs the tzinfo re-attached.
TW_TZ = timezone(timedelta(hours=8))


def get_taiwan_time():
    """Current time in the Taiwan timezone (UTC+8)."""
    return datetime.now(TW_TZ)


def tw_iso(dt):
    """Format a naive-UTC datetime from Postgres as a TW-tz ISO 8601 string.

    Returns None for None input so callers can pass column values straight in.
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(TW_TZ).isoformat()
