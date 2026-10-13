"""People and care-circle membership."""

from __future__ import annotations

from ..clock import Clock
from ..db import Database
from ..errors import Ambiguous, NotFound, ValidationError
from ..models import Person, Role
from ..timeutil import get_zone, to_iso


class PeopleService:
    def __init__(self, db: Database, clock: Clock, default_timezone: str) -> None:
        self._db = db
        self._clock = clock
        self._default_tz = default_timezone

    # -- create / read -------------------------------------------------------
    def create(
        self,
        name: str,
        role: Role | str,
        *,
        language: str = "en",
        timezone: str | None = None,
        telegram_chat_id: str | None = None,
    ) -> Person:
        name = (name or "").strip()
        if not name or len(name) > 80:
            raise ValidationError("Name must be 1-80 characters")
        role = Role(role)
        tz = timezone or self._default_tz
        get_zone(tz)
        if self._db.one("SELECT 1 FROM people WHERE lower(name) = lower(?)", (name,)):
            raise ValidationError(f"A person named {name!r} already exists")
        person_id = self._db.insert(
            "INSERT INTO people (name, role, language, timezone, telegram_chat_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, role.value, language, tz, telegram_chat_id, to_iso(self._clock.now())),
        )
        return self.get(person_id)

    def get(self, person_id: int) -> Person:
        row = self._db.one("SELECT * FROM people WHERE id = ?", (person_id,))
        if row is None:
            raise NotFound(f"No person with id {person_id}")
        return Person.from_row(row)

    def list(self, role: Role | str | None = None) -> list[Person]:
        if role is None:
            rows = self._db.all("SELECT * FROM people ORDER BY id")
        else:
            rows = self._db.all("SELECT * FROM people WHERE role = ? ORDER BY id", (Role(role).value,))
        return [Person.from_row(r) for r in rows]

    def find(self, query: str | int, role: Role | str | None = None) -> Person:
        """Resolve a spoken name or numeric id to exactly one person."""
        candidates = self.list(role)
        if isinstance(query, int) or str(query).strip().isdigit():
            wanted = int(query)
            for person in candidates:
                if person.id == wanted:
                    return person
            raise NotFound(f"No person with id {wanted}")
        needle = str(query).strip().casefold()
        if not needle:
            raise ValidationError("Person name must not be empty")
        exact = [p for p in candidates if p.name.casefold() == needle]
        if exact:
            return exact[0]
        partial = [p for p in candidates if needle in p.name.casefold()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise Ambiguous(f"More than one person matches {query!r}", [p.name for p in partial])
        raise NotFound(f"I couldn't find anyone called {query!r}")

    # -- circle membership ---------------------------------------------------
    def link(self, elder_id: int, member_id: int, relation: str | None = None) -> None:
        elder, member = self.get(elder_id), self.get(member_id)
        if elder.role is not Role.ELDER:
            raise ValidationError(f"{elder.name} is not an elder")
        if member.role is Role.ELDER:
            raise ValidationError("An elder cannot be a caregiver or family member of another elder")
        self._db.execute(
            "INSERT INTO care_links (elder_id, member_id, relation) VALUES (?, ?, ?)"
            " ON CONFLICT (elder_id, member_id) DO UPDATE SET relation = excluded.relation",
            (elder_id, member_id, relation),
        )

    def members_of(self, elder_id: int, role: Role | str | None = None) -> list[Person]:
        sql = (
            "SELECT p.* FROM people p JOIN care_links l ON l.member_id = p.id"
            " WHERE l.elder_id = ?"
        )
        params: list[object] = [elder_id]
        if role is not None:
            sql += " AND p.role = ?"
            params.append(Role(role).value)
        return [Person.from_row(r) for r in self._db.all(sql + " ORDER BY p.id", params)]

    def caregivers_of(self, elder_id: int) -> list[Person]:
        return self.members_of(elder_id, Role.CAREGIVER)

    def elders_of(self, member_id: int) -> list[Person]:
        rows = self._db.all(
            "SELECT p.* FROM people p JOIN care_links l ON l.elder_id = p.id"
            " WHERE l.member_id = ? ORDER BY p.id",
            (member_id,),
        )
        return [Person.from_row(r) for r in rows]

    def relation(self, elder_id: int, member_id: int) -> str | None:
        row = self._db.one(
            "SELECT relation FROM care_links WHERE elder_id = ? AND member_id = ?",
            (elder_id, member_id),
        )
        return row["relation"] if row else None

    def connected(self, a: int, b: int) -> bool:
        """True if two people share a circle (directly linked, or members of the same elder)."""
        if a == b:
            return True
        row = self._db.one(
            """
            SELECT 1 FROM care_links x WHERE
                (x.elder_id = :a AND x.member_id = :b) OR (x.elder_id = :b AND x.member_id = :a)
            UNION
            SELECT 1 FROM care_links x JOIN care_links y ON x.elder_id = y.elder_id
                WHERE x.member_id = :a AND y.member_id = :b
            LIMIT 1
            """,
            {"a": a, "b": b},
        )
        return row is not None

    def set_telegram_chat(self, person_id: int, chat_id: str | None) -> Person:
        self.get(person_id)
        self._db.execute("UPDATE people SET telegram_chat_id = ? WHERE id = ?", (chat_id, person_id))
        return self.get(person_id)
