"""Alert creation with de-duplication and delivery bookkeeping."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from ..clock import Clock
from ..db import Database
from ..errors import NotFound
from ..models import Alert, AlertKind, Person, Severity
from ..timeutil import to_iso
from .people import PeopleService


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RaisedAlert:
    alert: Alert
    created: bool  # False when an equivalent recent alert already existed


class AlertService:
    def __init__(
        self, db: Database, clock: Clock, people: PeopleService, dedupe_minutes: int
    ) -> None:
        self._db = db
        self._clock = clock
        self._people = people
        self._window = timedelta(minutes=dedupe_minutes)
        self._listeners: list[Callable[[Alert], None]] = []

    def add_listener(self, listener: Callable[[Alert], None]) -> None:
        """Called after a *new* alert is committed (e.g. to push a notification immediately)."""
        self._listeners.append(listener)

    def raise_alert(
        self,
        person_id: int,
        severity: Severity,
        kind: AlertKind,
        detail: str,
        *,
        dedupe_key: str | None = None,
    ) -> RaisedAlert:
        """Create an alert unless an equivalent one exists.

        * With ``dedupe_key`` the alert is unique per person (e.g. one missed-check-in per day).
        * Without it, an alert of the same kind and >= severity inside the window is reused,
          but a *more severe* alert always goes through (attention -> urgent escalates).
        """
        self._people.get(person_id)
        now = self._clock.now()
        with self._db.transaction():
            if dedupe_key is not None:
                row = self._db.one(
                    "SELECT * FROM alerts WHERE person_id = ? AND dedupe_key = ?",
                    (person_id, dedupe_key),
                )
                if row:
                    return RaisedAlert(Alert.from_row(row), False)
            else:
                row = self._db.one(
                    "SELECT * FROM alerts WHERE person_id = ? AND kind = ? AND severity >= ?"
                    " AND dedupe_key IS NULL AND created_at >= ? ORDER BY id DESC LIMIT 1",
                    (person_id, kind.value, int(severity), to_iso(now - self._window)),
                )
                if row:
                    return RaisedAlert(Alert.from_row(row), False)
            alert_id = self._db.insert(
                "INSERT INTO alerts (person_id, severity, kind, detail, created_at, dedupe_key)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (person_id, int(severity), kind.value, detail[:500], to_iso(now), dedupe_key),
            )
        alert = self.get(alert_id)
        for listener in self._listeners:
            try:
                listener(alert)
            except Exception:  # a broken notifier must never lose or block an alert
                log.exception("Alert listener failed for alert %s", alert_id)
        return RaisedAlert(alert, True)

    def get(self, alert_id: int) -> Alert:
        row = self._db.one("SELECT * FROM alerts WHERE id = ?", (alert_id,))
        if row is None:
            raise NotFound(f"No alert with id {alert_id}")
        return Alert.from_row(row)

    def list_for(self, person_id: int, *, since=None, limit: int = 50) -> list[Alert]:
        sql = "SELECT * FROM alerts WHERE person_id = ?"
        params: list[object] = [person_id]
        if since is not None:
            sql += " AND created_at >= ?"
            params.append(to_iso(since))
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [Alert.from_row(r) for r in self._db.all(sql, params)]

    def unnotified(self) -> list[Alert]:
        rows = self._db.all("SELECT * FROM alerts WHERE notified_at IS NULL ORDER BY severity DESC, id")
        return [Alert.from_row(r) for r in rows]

    def mark_notified(self, alert_id: int) -> None:
        self._db.execute(
            "UPDATE alerts SET notified_at = ? WHERE id = ? AND notified_at IS NULL",
            (to_iso(self._clock.now()), alert_id),
        )

    def acknowledge(self, alert_id: int) -> Alert:
        self.get(alert_id)
        self._db.execute(
            "UPDATE alerts SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
            (to_iso(self._clock.now()), alert_id),
        )
        return self.get(alert_id)

    def recipients(self, alert: Alert) -> list[Person]:
        """Who should hear about this alert: the elder's caregivers, falling back to family."""
        caregivers = self._people.caregivers_of(alert.person_id)
        return caregivers or self._people.members_of(alert.person_id)
