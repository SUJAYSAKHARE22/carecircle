"""Service container: one place that wires the whole care engine together."""

from __future__ import annotations

from dataclasses import dataclass

from concurrent.futures import Executor

from ..clock import Clock, OffsetClock, SystemClock
from ..config import Settings
from ..db import Database
from ..llm import LLMClient, LLMSecondOpinion
from ..notifier import Notifier, build_notifier
from ..safety import SafetyClassifier, SecondOpinion
from .alerts import AlertService
from .checkins import CheckinService
from .dispatcher import Dispatcher
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
    notifier: Notifier
    dispatcher: Dispatcher
    llm: LLMClient | None


def build_services(
    settings: Settings | None = None,
    *,
    db: Database | None = None,
    clock: Clock | None = None,
    second_opinion: SecondOpinion | None = None,
    notifier: Notifier | None = None,
    executor: Executor | None = None,
    llm: LLMClient | None = None,
) -> Services:
    settings = settings or Settings.from_env()
    clock = clock or (OffsetClock() if settings.demo_mode else SystemClock())
    db = db or Database(settings.db_path)
    llm = llm or LLMClient.from_settings(settings)
    if second_opinion is None and llm is not None:
        second_opinion = LLMSecondOpinion(llm)
    classifier = SafetyClassifier(second_opinion=second_opinion)
    people = PeopleService(db, clock, settings.timezone)
    alerts = AlertService(db, clock, people, settings.alert_dedupe_minutes)
    checkins = CheckinService(db, clock, people, alerts, classifier)
    reminders = ReminderService(db, clock, people)
    messages = MessageService(db, clock, people)
    summaries = SummaryService(clock, people, checkins, reminders, alerts, messages)
    monitor = Monitor(settings, clock, people, checkins, reminders, alerts)
    notifier = notifier or build_notifier(settings)
    dispatcher = Dispatcher(
        settings, clock, db, people, alerts, messages, summaries, notifier, executor
    )
    return Services(
        settings, clock, db, classifier, people, alerts, checkins,
        reminders, messages, summaries, monitor, notifier, dispatcher, llm,
    )


__all__ = ["Services", "build_services"]
