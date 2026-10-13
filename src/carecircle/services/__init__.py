"""Service container: one place that wires the whole care engine together."""

from __future__ import annotations

from dataclasses import dataclass

from ..clock import Clock, SystemClock
from ..config import Settings
from ..db import Database
from ..safety import SafetyClassifier, SecondOpinion
from .alerts import AlertService
from .checkins import CheckinService
from .messages import MessageService
from .monitor import Monitor
from .people import PeopleService
from .reminders import ReminderService
from .summaries import SummaryService


@dataclass(frozen=True)
class Services:
    settings: Settings
    clock: Clock
    db: Database
    classifier: SafetyClassifier
    people: PeopleService
    alerts: AlertService
    checkins: CheckinService
    reminders: ReminderService
    messages: MessageService
    summaries: SummaryService
    monitor: Monitor


def build_services(
    settings: Settings | None = None,
    *,
    db: Database | None = None,
    clock: Clock | None = None,
    second_opinion: SecondOpinion | None = None,
) -> Services:
    settings = settings or Settings.from_env()
    clock = clock or SystemClock()
    db = db or Database(settings.db_path)
    classifier = SafetyClassifier(second_opinion=second_opinion)
    people = PeopleService(db, clock, settings.timezone)
    alerts = AlertService(db, clock, people, settings.alert_dedupe_minutes)
    checkins = CheckinService(db, clock, people, alerts, classifier)
    reminders = ReminderService(db, clock, people)
    messages = MessageService(db, clock, people)
    summaries = SummaryService(clock, people, checkins, reminders, alerts, messages)
    monitor = Monitor(settings, clock, people, checkins, reminders, alerts)
    return Services(
        settings, clock, db, classifier, people, alerts, checkins,
        reminders, messages, summaries, monitor,
    )


__all__ = ["Services", "build_services"]
