"""Messages between people in the same care circle."""

from __future__ import annotations

from ..clock import Clock
from ..db import Database
from ..errors import NotFound, ValidationError
from ..models import Message
from ..timeutil import to_iso
from .people import PeopleService

MAX_BODY = 500


class MessageService:
    def __init__(self, db: Database, clock: Clock, people: PeopleService) -> None:
        self._db = db
        self._clock = clock
        self._people = people

    def send(self, from_id: int, to_id: int, body: str, *, private: bool = False) -> Message:
        sender, recipient = self._people.get(from_id), self._people.get(to_id)
        body = (body or "").strip()
        if not body:
            raise ValidationError("Message must not be empty")
        if len(body) > MAX_BODY:
            raise ValidationError(f"Message must be at most {MAX_BODY} characters")
        if not self._people.connected(sender.id, recipient.id):
            raise ValidationError(f"{sender.name} and {recipient.name} are not in the same care circle")
        message_id = self._db.insert(
            "INSERT INTO messages (from_id, to_id, body, created_at, private) VALUES (?, ?, ?, ?, ?)",
            (sender.id, recipient.id, body, to_iso(self._clock.now()), int(private)),
        )
        return self.get(message_id)

    def get(self, message_id: int) -> Message:
        row = self._db.one("SELECT * FROM messages WHERE id = ?", (message_id,))
        if row is None:
            raise NotFound(f"No message with id {message_id}")
        return Message.from_row(row)

    def unread_for(self, person_id: int) -> list[Message]:
        rows = self._db.all(
            "SELECT * FROM messages WHERE to_id = ? AND delivered_at IS NULL ORDER BY id", (person_id,)
        )
        return [Message.from_row(r) for r in rows]

    def take_inbox(self, person_id: int) -> list[Message]:
        """Return unread messages and mark them delivered, atomically (read-once semantics)."""
        now = to_iso(self._clock.now())
        with self._db.transaction():
            messages = self.unread_for(person_id)
            for m in messages:
                self._db.execute("UPDATE messages SET delivered_at = ? WHERE id = ?", (now, m.id))
        return messages

    def mark_delivered(self, message_id: int) -> None:
        self._db.execute(
            "UPDATE messages SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL",
            (to_iso(self._clock.now()), message_id),
        )

    def between_for_day(self, person_id: int, start, end) -> list[Message]:
        rows = self._db.all(
            "SELECT * FROM messages WHERE (to_id = ? OR from_id = ?) AND created_at >= ? AND created_at < ?"
            " ORDER BY id",
            (person_id, person_id, to_iso(start), to_iso(end)),
        )
        return [Message.from_row(r) for r in rows]
