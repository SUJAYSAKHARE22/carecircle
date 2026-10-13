"""Immutable domain models. Datetimes are timezone-aware UTC."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any

from .timeutil import from_iso


class Role(str, Enum):
    ELDER = "elder"
    CAREGIVER = "caregiver"
    FAMILY = "family"


class Severity(IntEnum):
    INFO = 0
    ATTENTION = 1
    URGENT = 2

    @property
    def label(self) -> str:
        return self.name.lower()


class AlertKind(str, Enum):
    SAFETY = "safety"
    MISSED_CHECKIN = "missed_checkin"
    MISSED_REMINDER = "missed_reminder"
    MANUAL = "manual"


class ReminderStatus(str, Enum):
    PENDING = "pending"
    TAKEN = "taken"
    SKIPPED = "skipped"
    MISSED = "missed"


def _opt(value: str | None) -> datetime | None:
    return from_iso(value) if value else None


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    role: Role
    language: str
    timezone: str
    telegram_chat_id: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Person":
        return cls(
            id=row["id"],
            name=row["name"],
            role=Role(row["role"]),
            language=row["language"],
            timezone=row["timezone"],
            telegram_chat_id=row["telegram_chat_id"],
            created_at=from_iso(row["created_at"]),
        )


@dataclass(frozen=True)
class Checkin:
    id: int
    person_id: int
    ts: datetime
    note: str
    mood: int | None
    severity: Severity

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Checkin":
        return cls(
            id=row["id"],
            person_id=row["person_id"],
            ts=from_iso(row["ts"]),
            note=row["note"],
            mood=row["mood"],
            severity=Severity(row["severity"]),
        )


@dataclass(frozen=True)
class Reminder:
    id: int
    person_id: int
    title: str
    at_time: str
    days: tuple[int, ...]
    created_by: int | None
    active: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Reminder":
        return cls(
            id=row["id"],
            person_id=row["person_id"],
            title=row["title"],
            at_time=row["at_time"],
            days=tuple(int(d) for d in row["days"].split(",") if d != ""),
            created_by=row["created_by"],
            active=bool(row["active"]),
        )


@dataclass(frozen=True)
class ReminderEvent:
    id: int
    reminder_id: int
    person_id: int
    title: str
    due_at: datetime
    status: ReminderStatus
    responded_at: datetime | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ReminderEvent":
        return cls(
            id=row["id"],
            reminder_id=row["reminder_id"],
            person_id=row["person_id"],
            title=row["title"],
            due_at=from_iso(row["due_at"]),
            status=ReminderStatus(row["status"]),
            responded_at=_opt(row["responded_at"]),
        )


@dataclass(frozen=True)
class Message:
    id: int
    from_id: int
    to_id: int
    body: str
    created_at: datetime
    delivered_at: datetime | None
    private: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Message":
        return cls(
            id=row["id"],
            from_id=row["from_id"],
            to_id=row["to_id"],
            body=row["body"],
            created_at=from_iso(row["created_at"]),
            delivered_at=_opt(row["delivered_at"]),
            private=bool(row["private"]),
        )


@dataclass(frozen=True)
class Alert:
    id: int
    person_id: int
    severity: Severity
    kind: AlertKind
    detail: str
    created_at: datetime
    notified_at: datetime | None
    acknowledged_at: datetime | None
    dedupe_key: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Alert":
        return cls(
            id=row["id"],
            person_id=row["person_id"],
            severity=Severity(row["severity"]),
            kind=AlertKind(row["kind"]),
            detail=row["detail"],
            created_at=from_iso(row["created_at"]),
            notified_at=_opt(row["notified_at"]),
            acknowledged_at=_opt(row["acknowledged_at"]),
            dedupe_key=row["dedupe_key"],
        )


def public(data: dict[str, Any]) -> dict[str, Any]:
    """Drop None values for compact tool results."""
    return {k: v for k, v in data.items() if v is not None}
