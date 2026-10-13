"""Small, well-tested time helpers. Storage is always UTC ISO-8601."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ValidationError

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(value: str) -> time:
    match = _HHMM.match(value.strip())
    if not match:
        raise ValidationError(f"Time must be HH:MM in 24-hour format, got {value!r}")
    return time(int(match.group(1)), int(match.group(2)))


def format_hhmm(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"Unknown timezone {name!r}") from exc


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Naive datetimes are not allowed")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def local_date(value: datetime, zone: ZoneInfo) -> date:
    return value.astimezone(zone).date()


def local_day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Return [start, end) of a local calendar day expressed in UTC."""
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def local_moment(day: date, at: time, zone: ZoneInfo) -> datetime:
    """A local wall-clock time on a given local day, as UTC."""
    return datetime.combine(day, at, tzinfo=zone).astimezone(timezone.utc)


def humanize_time(value: datetime, zone: ZoneInfo) -> str:
    local = value.astimezone(zone)
    hour = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    return f"{hour}:{local.minute:02d} {suffix}"
