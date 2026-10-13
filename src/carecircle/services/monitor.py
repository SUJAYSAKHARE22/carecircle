"""Escalation engine: missed check-ins and missed reminders.

Run periodically (Stage 4 scheduler). Each run is idempotent:
  * Before the deadline            -> nothing.
  * Deadline .. deadline + grace   -> a single gentle nudge to the elder.
  * After the grace period         -> one 'missed check-in' alert per day.
  * Reminders unanswered past grace -> marked missed, one alert per event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from ..clock import Clock
from ..config import Settings
from ..models import AlertKind, Person, ReminderEvent, Role, Severity
from ..timeutil import get_zone, humanize_time, local_date, local_moment
from .alerts import AlertService, RaisedAlert
from .checkins import CheckinService
from .people import PeopleService
from .reminders import ReminderService


@dataclass(frozen=True)
class Nudge:
    person_id: int
    reason: str


@dataclass(frozen=True)
class CheckinStatus:
    person: Person
    state: Literal["ok", "due", "missed"]
    deadline: datetime


@dataclass(frozen=True)
class MonitorReport:
    nudges: tuple[Nudge, ...] = field(default_factory=tuple)
    alerts: tuple[RaisedAlert, ...] = field(default_factory=tuple)
    missed_events: tuple[ReminderEvent, ...] = field(default_factory=tuple)


class Monitor:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        people: PeopleService,
        checkins: CheckinService,
        reminders: ReminderService,
        alerts: AlertService,
    ) -> None:
        self._s = settings
        self._clock = clock
        self._people = people
        self._checkins = checkins
        self._reminders = reminders
        self._alerts = alerts
        self._nudged: set[tuple[int, date]] = set()

    def checkin_statuses(self) -> list[CheckinStatus]:
        """Read-only view: who has / hasn't checked in relative to today's deadline."""
        now = self._clock.now()
        statuses: list[CheckinStatus] = []
        for elder in self._people.list(Role.ELDER):
            zone = get_zone(elder.timezone)
            deadline = local_moment(local_date(now, zone), self._s.checkin_deadline, zone)
            if now < deadline or self._checkins.has_checked_in_today(elder.id):
                state = "ok"
            elif now < deadline + timedelta(minutes=self._s.grace_minutes):
                state = "due"
            else:
                state = "missed"
            statuses.append(CheckinStatus(elder, state, deadline))
        return statuses

    def run(self) -> MonitorReport:
        now = self._clock.now()
        nudges: list[Nudge] = []
        raised: list[RaisedAlert] = []

        for status in self.checkin_statuses():
            elder = status.person
            zone = get_zone(elder.timezone)
            today = local_date(now, zone)
            self._reminders.materialize(elder.id, today)
            if status.state == "due" and (elder.id, today) not in self._nudged:
                self._nudged.add((elder.id, today))
                nudges.append(Nudge(elder.id, "checkin_due"))
            elif status.state == "missed":
                raised.append(
                    self._alerts.raise_alert(
                        elder.id,
                        Severity.ATTENTION,
                        AlertKind.MISSED_CHECKIN,
                        f"{elder.name} has not checked in today "
                        f"(expected by {humanize_time(status.deadline, zone)}).",
                        dedupe_key=f"missed_checkin:{today.isoformat()}",
                    )
                )

        missed = self._reminders.mark_overdue(self._s.reminder_grace_minutes)
        for event in missed:
            person = self._people.get(event.person_id)
            zone = get_zone(person.timezone)
            raised.append(
                self._alerts.raise_alert(
                    event.person_id,
                    Severity.ATTENTION,
                    AlertKind.MISSED_REMINDER,
                    f"{person.name} did not confirm \u201c{event.title}\u201d "
                    f"(due {humanize_time(event.due_at, zone)}).",
                    dedupe_key=f"missed_reminder:{event.id}",
                )
            )
        return MonitorReport(tuple(nudges), tuple(raised), tuple(missed))
