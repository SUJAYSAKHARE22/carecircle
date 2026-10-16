"""Turns monitor findings and stored alerts into notifications, exactly once."""

from __future__ import annotations

import logging
from concurrent.futures import Executor
from dataclasses import dataclass

from ..clock import Clock
from ..config import Settings
from ..db import Database
from ..i18n import t
from ..models import Alert, Role
from ..notifier import Notifier, format_alert
from ..timeutil import get_zone, local_date, local_moment, to_iso
from .alerts import AlertService
from .messages import MessageService
from .monitor import MonitorReport
from .people import PeopleService
from .summaries import SummaryService

log = logging.getLogger("carecircle.dispatch")


@dataclass(frozen=True)
class DispatchReport:
    alerts_sent: int = 0
    alerts_pending: int = 0
    messages_sent: int = 0
    digests_sent: int = 0
    nudges_sent: int = 0


class Dispatcher:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        db: Database,
        people: PeopleService,
        alerts: AlertService,
        messages: MessageService,
        summaries: SummaryService,
        notifier: Notifier,
        executor: Executor | None = None,
    ) -> None:
        self._s = settings
        self._clock = clock
        self._db = db
        self._people = people
        self._alerts = alerts
        self._messages = messages
        self._summaries = summaries
        self._notifier = notifier
        self._executor = executor
        # Push urgent news immediately instead of waiting for the next scheduler tick.
        alerts.add_listener(self._on_new_alert)

    # -- immediate path ------------------------------------------------------------
    def _on_new_alert(self, alert: Alert) -> None:
        if self._executor is None:
            self.flush_alerts()
        else:
            self._executor.submit(self._safe_flush)

    def _safe_flush(self) -> None:
        try:
            self.flush_alerts()
        except Exception:
            log.exception("Background alert flush failed")

    # -- periodic path ---------------------------------------------------------------
    def dispatch(self, report: MonitorReport) -> DispatchReport:
        nudges = self._send_nudges(report)
        alerts_sent, pending = self.flush_alerts_counted()
        return DispatchReport(
            alerts_sent=alerts_sent,
            alerts_pending=pending,
            messages_sent=self.flush_messages(),
            digests_sent=self.send_digests(),
            nudges_sent=nudges,
        )

    def flush_alerts(self) -> int:
        return self.flush_alerts_counted()[0]

    def flush_alerts_counted(self) -> tuple[int, int]:
        sent = pending = 0
        for alert in self._alerts.unnotified():
            recipients = self._alerts.recipients(alert)
            text = format_alert(alert)
            delivered = sum(1 for r in recipients if self._notifier.send(r, text))
            if delivered:
                self._alerts.mark_notified(alert.id)
                sent += 1
            else:
                pending += 1
                log.warning("Alert %s could not be delivered to anyone yet", alert.id)
        return sent, pending

    def flush_messages(self) -> int:
        sent = 0
        for message in self._messages.undelivered_for_remote():
            recipient = self._people.get(message.to_id)
            sender = self._people.get(message.from_id)
            if self._notifier.send(recipient, f"\U0001F4AC Message from {sender.name}:\n{message.body}"):
                self._messages.mark_delivered(message.id)
                sent += 1
        return sent

    def send_digests(self) -> int:
        now = self._clock.now()
        sent = 0
        for elder in self._people.list(Role.ELDER):
            zone = get_zone(elder.timezone)
            today = local_date(now, zone)
            if now < local_moment(today, self._s.digest_time, zone):
                continue
            if self._db.one(
                "SELECT 1 FROM digests WHERE person_id = ? AND day = ?", (elder.id, today.isoformat())
            ):
                continue
            recipients = self._people.caregivers_of(elder.id) or self._people.members_of(elder.id)
            text = f"\U0001F319 Daily summary \u2014 {elder.name}\n{self._summaries.build(elder.id, today).to_text()}"
            delivered = sum(1 for r in recipients if self._notifier.send(r, text))
            if delivered or not recipients:
                self._db.execute(
                    "INSERT OR IGNORE INTO digests (person_id, day, sent_at) VALUES (?, ?, ?)",
                    (elder.id, today.isoformat(), to_iso(now)),
                )
                sent += 1 if delivered else 0
        return sent

    def _send_nudges(self, report: MonitorReport) -> int:
        sent = 0
        for nudge in report.nudges:
            elder = self._people.get(nudge.person_id)
            if self._notifier.send(elder, t(elder.language, "nudge", name=elder.name)):
                sent += 1
        return sent
