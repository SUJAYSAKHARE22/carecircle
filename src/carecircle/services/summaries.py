"""Plain-language daily digests for caregivers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ..clock import Clock
from ..models import Alert, Checkin, Message, Person, ReminderEvent, ReminderStatus, Severity
from ..timeutil import get_zone, humanize_time, local_date, local_day_bounds
from .alerts import AlertService
from .checkins import MOOD_LABELS, CheckinService
from .messages import MessageService
from .people import PeopleService
from .reminders import ReminderService


@dataclass(frozen=True)
class DaySummary:
    person: Person
    day: date
    checkins: tuple[Checkin, ...]
    events: tuple[ReminderEvent, ...]
    alerts: tuple[Alert, ...]
    messages_to: int
    messages_from: int

    @property
    def mood_average(self) -> float | None:
        moods = [c.mood for c in self.checkins if c.mood is not None]
        return round(sum(moods) / len(moods), 1) if moods else None

    def count(self, status: ReminderStatus) -> int:
        return sum(1 for e in self.events if e.status is status)

    def to_dict(self) -> dict:
        zone = get_zone(self.person.timezone)
        avg = self.mood_average
        return {
            "person": self.person.name,
            "date": self.day.isoformat(),
            "checked_in": bool(self.checkins),
            "first_checkin": humanize_time(self.checkins[0].ts, zone) if self.checkins else None,
            "mood_average": avg,
            "mood_label": MOOD_LABELS[round(avg)] if avg is not None else None,
            "reminders": {
                "total": len(self.events),
                "taken": self.count(ReminderStatus.TAKEN),
                "skipped": self.count(ReminderStatus.SKIPPED),
                "missed": self.count(ReminderStatus.MISSED),
                "pending": self.count(ReminderStatus.PENDING),
            },
            "concerns": [
                {
                    "severity": a.severity.label,
                    "kind": a.kind.value,
                    "time": humanize_time(a.created_at, zone),
                    "detail": a.detail,
                }
                for a in self.alerts
            ],
            "messages": {"received": self.messages_to, "sent": self.messages_from},
            "text": self.to_text(),
        }

    def to_text(self) -> str:
        zone = get_zone(self.person.timezone)
        name = self.person.name
        parts: list[str] = []
        if self.checkins:
            first = humanize_time(self.checkins[0].ts, zone)
            avg = self.mood_average
            mood = f", feeling {MOOD_LABELS[round(avg)]}" if avg is not None else ""
            extra = f" ({len(self.checkins)} check-ins)" if len(self.checkins) > 1 else ""
            parts.append(f"{name} first checked in at {first}{mood}{extra}.")
        else:
            parts.append(f"{name} has not checked in.")
        if self.events:
            taken, total = self.count(ReminderStatus.TAKEN), len(self.events)
            line = f"Reminders: {taken} of {total} confirmed"
            missed = self.count(ReminderStatus.MISSED)
            skipped = self.count(ReminderStatus.SKIPPED)
            pending = self.count(ReminderStatus.PENDING)
            extras = [f"{n} {label}" for n, label in ((missed, "missed"), (skipped, "skipped"), (pending, "still pending")) if n]
            parts.append(line + (f" ({', '.join(extras)})." if extras else "."))
        concerns = [a for a in self.alerts if a.severity >= Severity.ATTENTION]
        if concerns:
            top = max(concerns, key=lambda a: a.severity)
            parts.append(
                f"{len(concerns)} concern{'s' if len(concerns) != 1 else ''} noted, "
                f"highest was {top.severity.label} at {humanize_time(top.created_at, zone)}."
            )
        else:
            parts.append("No concerns noted.")
        if self.messages_to or self.messages_from:
            parts.append(f"Messages: {self.messages_to} received, {self.messages_from} sent.")
        return " ".join(parts)


class SummaryService:
    def __init__(
        self,
        clock: Clock,
        people: PeopleService,
        checkins: CheckinService,
        reminders: ReminderService,
        alerts: AlertService,
        messages: MessageService,
    ) -> None:
        self._clock = clock
        self._people = people
        self._checkins = checkins
        self._reminders = reminders
        self._alerts = alerts
        self._messages = messages

    def build(self, person_id: int, day: date | None = None) -> DaySummary:
        person = self._people.get(person_id)
        zone = get_zone(person.timezone)
        day = day or local_date(self._clock.now(), zone)
        start, end = local_day_bounds(day, zone)
        alerts = [a for a in self._alerts.list_for(person_id, since=start, limit=200) if a.created_at < end]
        messages = self._messages.between_for_day(person_id, start, end)
        return DaySummary(
            person=person,
            day=day,
            checkins=tuple(self._checkins.for_day(person_id, day)),
            events=tuple(self._reminders.events_for_day(person_id, day)),
            alerts=tuple(sorted(alerts, key=lambda a: a.created_at)),
            messages_to=sum(1 for m in messages if m.to_id == person_id),
            messages_from=sum(1 for m in messages if m.from_id == person_id),
        )
