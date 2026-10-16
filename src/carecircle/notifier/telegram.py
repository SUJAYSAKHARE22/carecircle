"""Telegram delivery plus a tiny command bot for caregivers (free, no hosting needed)."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

import httpx

from ..errors import CareCircleError
from ..models import Person

if TYPE_CHECKING:
    from ..services import Services

log = logging.getLogger("carecircle.telegram")
API = "https://api.telegram.org"
MAX_LEN = 4000  # Telegram hard limit is 4096


class TelegramClient:
    def __init__(self, token: str, http: httpx.Client | None = None) -> None:
        if not token:
            raise ValueError("Telegram bot token is required")
        # httpx logs full request URLs at INFO, and the token is part of the URL.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self._base = f"{API}/bot{token}"
        self._http = http or httpx.Client(timeout=httpx.Timeout(10.0, read=40.0))

    def send_message(self, chat_id: str, text: str) -> bool:
        try:
            response = self._http.post(
                f"{self._base}/sendMessage", json={"chat_id": chat_id, "text": text[:MAX_LEN]}
            )
        except httpx.HTTPError as exc:
            log.warning("Telegram send failed: %s", type(exc).__name__)
            return False
        if not response.is_success:
            log.warning("Telegram rejected message (HTTP %s)", response.status_code)
        return response.is_success

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        response = self._http.get(f"{self._base}/getUpdates", params=params)
        response.raise_for_status()
        return list(response.json().get("result", []))


class TelegramNotifier:
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    def send(self, person: Person, text: str) -> bool:
        if not person.telegram_chat_id:
            log.info("No Telegram chat linked for %s; message not delivered", person.name)
            return False
        return self._client.send_message(person.telegram_chat_id, text)


class BotCommands:
    """Pure command logic (no network), so it is fully unit-testable."""

    def __init__(self, services: Services) -> None:
        self._s = services

    def handle(self, chat_id: str, text: str) -> str | None:
        text = (text or "").strip()
        if not text.startswith("/"):
            return None
        command, _, arg = text.partition(" ")
        command = command.split("@")[0].lower()
        person = self._s.people.find_by_chat(chat_id)
        try:
            if command in ("/start", "/help"):
                return self._start(chat_id, person)
            if person is None:
                return "This chat isn't linked yet. " + self._link_hint(chat_id)
            if command == "/status":
                return self._status(person)
            if command == "/ack":
                return self._ack(person, arg.strip())
        except CareCircleError as exc:
            return f"Sorry: {exc}"
        return "Unknown command. Try /status, /ack <id> or /help."

    @staticmethod
    def _link_hint(chat_id: str) -> str:
        return f"Your chat id is {chat_id}. Ask the family admin to run: carecircle link-telegram <YourName> {chat_id}"

    def _start(self, chat_id: str, person: Person | None) -> str:
        if person is None:
            return "Welcome to CareCircle. " + self._link_hint(chat_id)
        return (
            f"Hi {person.name}. You'll get alerts and a daily summary here.\n"
            "/status - today's summary\n/ack <id> - mark an alert as handled"
        )

    def _status(self, person: Person) -> str:
        elders = self._s.people.elders_of(person.id) if person.role.value != "elder" else [person]
        if not elders:
            return "You're not linked to anyone yet."
        return "\n\n".join(
            f"{e.name}: {self._s.summaries.build(e.id).to_text()}" for e in elders
        )

    def _ack(self, person: Person, arg: str) -> str:
        if not arg.isdigit():
            return "Usage: /ack <alert id>"
        alert = self._s.alerts.get(int(arg))
        allowed = {m.id for m in self._s.people.members_of(alert.person_id)}
        if person.id not in allowed:
            return "That alert isn't for someone in your circle."
        self._s.alerts.acknowledge(alert.id)
        return f"Alert {alert.id} marked as handled. Thank you."


class TelegramPoller(threading.Thread):
    """Long-polls Telegram and answers commands. Runs as a daemon thread."""

    def __init__(self, client: TelegramClient, commands: BotCommands) -> None:
        super().__init__(name="telegram-poller", daemon=True)
        self._client = client
        self._commands = commands
        self._halt = threading.Event()
        self._offset: int | None = None

    def stop(self) -> None:
        self._halt.set()

    def poll_once(self, timeout: int = 25) -> int:
        handled = 0
        for update in self._client.get_updates(self._offset, timeout):
            self._offset = int(update["update_id"]) + 1
            message = update.get("message") or {}
            chat_id = str((message.get("chat") or {}).get("id", ""))
            reply = self._commands.handle(chat_id, message.get("text", "")) if chat_id else None
            if reply:
                self._client.send_message(chat_id, reply)
                handled += 1
        return handled

    def run(self) -> None:  # pragma: no cover - network loop
        backoff = 1.0
        while not self._halt.is_set():
            try:
                self.poll_once()
                backoff = 1.0
            except Exception as exc:
                log.warning("Telegram polling error (%s); retrying in %.0fs", type(exc).__name__, backoff)
                self._halt.wait(backoff)
                backoff = min(backoff * 2, 60.0)
