"""Notification channel abstraction."""

from __future__ import annotations

import logging
from typing import Protocol

from ..models import Alert, Person, Severity

log = logging.getLogger("carecircle.notify")

_ICONS = {Severity.URGENT: "\U0001F6A8", Severity.ATTENTION: "\u26A0\uFE0F", Severity.INFO: "\u2139\uFE0F"}


class Notifier(Protocol):
    def send(self, person: Person, text: str) -> bool:
        """Deliver `text` to `person`. Return True only if it was actually delivered."""
        ...


class ConsoleNotifier:
    """Zero-config fallback: writes notifications to the log. Always 'succeeds'."""

    def send(self, person: Person, text: str) -> bool:
        log.info("[notify -> %s] %s", person.name, text.replace("\n", " | "))
        return True


class RecordingNotifier:
    """Captures notifications in memory. Handy for tests and demos."""

    def __init__(self, deliverable: bool = True) -> None:
        self.sent: list[tuple[str, str]] = []
        self.deliverable = deliverable

    def send(self, person: Person, text: str) -> bool:
        if not self.deliverable:
            return False
        self.sent.append((person.name, text))
        return True


def format_alert(alert: Alert) -> str:
    return (
        f"{_ICONS[alert.severity]} {alert.severity.label.upper()} alert\n"
        f"{alert.detail}\n"
        f"Reply /ack {alert.id} once this is handled."
    )
