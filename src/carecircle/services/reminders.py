"""Recurring reminders and per-day confirmation events."""

from __future__ import annotations

import re
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Sequence

from ..clock import Clock
from ..db import Database
from ..errors import Ambiguous, NotFound, ValidationError
from ..models import Reminder, ReminderEvent, ReminderStatus
from ..timeutil import (
    format_hhmm, get_zone, local_date, local_day_bounds, local_moment, parse_hhmm, to_iso,
)
from .people import PeopleService

_EVENT_SQL = (
    "SELECT e.*, r.title AS title FROM reminder_events e"
    " JOIN reminders r ON r.id = e.reminder_id"
)
_WORD = re.compile(r"[^\s.,;:!?()\"\u201c\u201d]+")  # \w splits Devanagari at matras
_MATCH_FLOOR = 0.45


def _score(hint: str, title: str) -> float:
    h, t = hint.casefold().strip(), title.casefold().strip()
    if not h or not t:
        return 0.0
    if h in t or t in h:
        return 1.0
    hw, tw = set(_WORD.findall(h)), set(_WORD.findall(t))
    overlap = len(hw & tw) / max(1, min(len(hw), len(tw)))
    return max(overlap, SequenceMatcher(None, h, t).ratio())


class ReminderService:
    def __init__(self, db: Database, clock: Clock, people: PeopleService) -> None:
        self._db = db
        self._clock = clock
        self._people = people

    # -- definitions -----------------------------------------------------------
    def create(
        self,
        person_id: int,
        title: str,
        at_time: str,
        *,
        days: Sequence[int] | None = None,
        created_by: int | None = None,
    ) -> Reminder:
        person = self._people.get(person_id)
        title = (title or "").strip()
        if not title or len(title) > 120:
            raise ValidationError("Reminder title must be 1-120 characters")
        at = parse_hhmm(at_time)
        day_set = sorted(set(days)) if days else list(range(7))
        if any(d not in range(7) for d in day_set):
            raise ValidationError("Days must be integers 0 (Monday) to 6 (Sunday)")
        if created_by is not None:
            self._people.get(created_by)
        with self._db.transaction():
            reminder_id = self._db.insert(
                "INSERT INTO reminders (person_id, title, at_time, days, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (person_id, title, format_hhmm(at), ",".join(map(str, day_set)),
                 created_by, to_iso(self._clock.now())),
            )
            zone = get_zone(person.timezone)
            self.materialize(person_id, local_date(self._clock.now(), zone))
        return self.get(reminder_id)

    def get(self, reminder_id: int) -> Reminder:
        row = self._db.one("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        if row is None:
            raise NotFound(f"No reminder with id {reminder_id}")
        return Reminder.from_row(row)

    def list(self, person_id: int, *, active_only: bool = True) -> list[Reminder]:
        sql = "SELECT * FROM reminders WHERE person_id = ?"
        if active_only:
            sql += " AND active = 1"
        return [Reminder.from_row(r) for r in self._db.all(sql + " ORDER BY at_time, id", (person_id,))]

    def deactivate(self, reminder_id: int) -> Reminder:
        self.get(reminder_id)
        with self._db.transaction():
            self._db.execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,))
            self._db.execute(
                "DELETE FROM reminder_events WHERE reminder_id = ? AND status = 'pending' AND due_at > ?",
                (reminder_id, to_iso(self._clock.now())),
            )
        return self.get(reminder_id)

    # -- daily events ------------------------------------------------------------
    def materialize(self, person_id: int, day: date) -> int:
        """Create (idempotently) the confirmation events for one local day.

        A reminder never owes an occurrence that fell due before it was created, so setting up
        an 08:00 routine at 20:00 does not instantly produce a 'missed' dose.
        """
        zone = get_zone(self._people.get(person_id).timezone)
        created = 0
        for reminder in self.list(person_id):
            if day.weekday() not in reminder.days:
                continue
            due = local_moment(day, parse_hhmm(reminder.at_time), zone)
            if due < reminder.created_at:
                continue
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO reminder_events (reminder_id, person_id, due_at)"
                " VALUES (?, ?, ?)",
                (reminder.id, person_id, to_iso(due)),
            )
            created += cursor.rowcount
        return created

    def events_for_day(self, person_id: int, day: date) -> list[ReminderEvent]:
        zone = get_zone(self._people.get(person_id).timezone)
        start, end = local_day_bounds(day, zone)
        rows = self._db.all(
            f"{_EVENT_SQL} WHERE e.person_id = ? AND e.due_at >= ? AND e.due_at < ? ORDER BY e.due_at",
            (person_id, to_iso(start), to_iso(end)),
        )
        return [ReminderEvent.from_row(r) for r in rows]

    def due_events(self, person_id: int, *, lookahead_minutes: int = 30) -> list[ReminderEvent]:
        """Pending events due now (or within the lookahead) on the person's current local day."""
        now = self._clock.now()
        zone = get_zone(self._people.get(person_id).timezone)
        start, _ = local_day_bounds(local_date(now, zone), zone)
        rows = self._db.all(
            f"{_EVENT_SQL} WHERE e.person_id = ? AND e.status = 'pending'"
            " AND e.due_at >= ? AND e.due_at <= ? ORDER BY e.due_at",
            (person_id, to_iso(start), to_iso(now + timedelta(minutes=lookahead_minutes))),
        )
        return [ReminderEvent.from_row(r) for r in rows]

    def respond(
        self,
        person_id: int,
        status: ReminderStatus | str,
        title_hint: str | None = None,
        *,
        lookahead_minutes: int = 60,
    ) -> ReminderEvent:
        status = ReminderStatus(status)
        if status not in (ReminderStatus.TAKEN, ReminderStatus.SKIPPED):
            raise ValidationError("A reminder can only be answered as 'taken' or 'skipped'")
        candidates = self.due_events(person_id, lookahead_minutes=lookahead_minutes)
        if not candidates:
            raise NotFound("There is nothing waiting to be confirmed right now")
        hint = (title_hint or "").strip()
        if hint:
            scored = sorted(((_score(hint, c.title), c) for c in candidates), key=lambda x: -x[0])
            best_score, best = scored[0]
            if best_score < _MATCH_FLOOR:
                raise NotFound(f"I couldn't match {hint!r} to a pending reminder")
            close = [c for s, c in scored if best_score - s < 0.1]
            if len(close) > 1:
                raise Ambiguous("More than one reminder matches", [c.title for c in close])
            chosen = best
        elif len(candidates) == 1:
            chosen = candidates[0]
        else:
            raise Ambiguous("More than one reminder is waiting", [c.title for c in candidates])
        self._db.execute(
            "UPDATE reminder_events SET status = ?, responded_at = ? WHERE id = ?",
            (status.value, to_iso(self._clock.now()), chosen.id),
        )
        return self._event(chosen.id)

    def mark_overdue(self, grace_minutes: int) -> list[ReminderEvent]:
        """Flip pending events past their grace period to 'missed' and return them."""
        cutoff = to_iso(self._clock.now() - timedelta(minutes=grace_minutes))
        with self._db.transaction():
            rows = self._db.all(
                f"{_EVENT_SQL} WHERE e.status = 'pending' AND e.due_at < ? ORDER BY e.due_at",
                (cutoff,),
            )
            for row in rows:
                self._db.execute("UPDATE reminder_events SET status = 'missed' WHERE id = ?", (row["id"],))
        return [self._event(r["id"]) for r in rows]

    def _event(self, event_id: int) -> ReminderEvent:
        row = self._db.one(f"{_EVENT_SQL} WHERE e.id = ?", (event_id,))
        if row is None:
            raise NotFound(f"No reminder event with id {event_id}")
        return ReminderEvent.from_row(row)
