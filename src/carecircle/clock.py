"""Injectable clock so time-dependent logic is deterministic under test."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:  # timezone-aware, UTC
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """A manually advanced clock for tests and demos."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = start.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value.astimezone(timezone.utc)

    def advance(self, **delta: float) -> datetime:
        self._now += timedelta(**delta)
        return self._now


class OffsetClock:
    """System time plus a movable offset. Used by demo mode to 'time travel' safely."""

    def __init__(self) -> None:
        self._offset = timedelta(0)

    @property
    def offset(self) -> timedelta:
        return self._offset

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self._offset

    def advance(self, **delta: float) -> datetime:
        self._offset += timedelta(**delta)
        return self.now()

    def reset(self) -> None:
        self._offset = timedelta(0)
