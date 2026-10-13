"""Forgiving parsers for values that arrive from a voice assistant."""

from __future__ import annotations

from typing import Iterable

from .errors import ValidationError

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_GROUPS = {
    "daily": tuple(range(7)),
    "everyday": tuple(range(7)),
    "every day": tuple(range(7)),
    "weekdays": (0, 1, 2, 3, 4),
    "weekday": (0, 1, 2, 3, 4),
    "weekends": (5, 6),
    "weekend": (5, 6),
}


def _one(token: str) -> tuple[int, ...]:
    text = token.strip().casefold()
    if not text:
        return ()
    if text in _GROUPS:
        return _GROUPS[text]
    if text.isdigit():
        return (int(text),)
    if text[:3] in _DAY_NAMES:
        return (_DAY_NAMES.index(text[:3]),)
    raise ValidationError(f"I didn't understand the day {token!r}")


def parse_days(value: str | int | Iterable[str | int] | None) -> list[int] | None:
    """Accept 'daily', 'weekdays', 'mon,wed,fri', ['Monday', 2], or None (= every day)."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValidationError("Days must be names or numbers")
    if isinstance(value, int):
        parts: list[str | int] = [value]
    elif isinstance(value, str):
        parts = value.replace(" and ", ",").split(",")
    else:
        parts = list(value)
    days: set[int] = set()
    for part in parts:
        days.update(_one(str(part)))
    if not days:
        return None
    if any(d not in range(7) for d in days):
        raise ValidationError("Days must be 0 (Monday) to 6 (Sunday)")
    return sorted(days)
