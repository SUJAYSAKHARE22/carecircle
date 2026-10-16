"""Daily check-ins with automatic concern detection."""

from __future__ import annotations

from dataclasses import dataclass

from ..clock import Clock
from ..db import Database
from ..errors import ValidationError
from ..models import AlertKind, Checkin
from ..safety import Assessment, SafetyClassifier
from ..timeutil import get_zone, local_date, local_day_bounds, to_iso
from .alerts import AlertService, RaisedAlert
from .people import PeopleService

MOOD_LABELS = {1: "very low", 2: "low", 3: "okay", 4: "good", 5: "great"}
_MOOD_WORDS = {
    "terrible": 1, "awful": 1, "very low": 1, "very bad": 1,
    "bad": 2, "low": 2, "sad": 2, "tired": 2, "unwell": 2,
    "okay": 3, "ok": 3, "so-so": 3, "alright": 3, "average": 3,
    "good": 4, "fine": 4, "well": 4, "happy": 4,
    "great": 5, "excellent": 5, "wonderful": 5, "very good": 5,
}
MAX_NOTE = 600


def parse_mood(value: int | str | None) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        mood = value
    else:
        text = str(value).strip().casefold()
        if text.isdigit():
            mood = int(text)
        elif text in _MOOD_WORDS:
            mood = _MOOD_WORDS[text]
        else:
            raise ValidationError(f"Mood must be 1-5 or a word like 'good', got {value!r}")
    if not 1 <= mood <= 5:
        raise ValidationError("Mood must be between 1 (very low) and 5 (great)")
    return mood


@dataclass(frozen=True)
class CheckinResult:
    checkin: Checkin
    assessment: Assessment
    alert: RaisedAlert | None
    first_today: bool


class CheckinService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        people: PeopleService,
        alerts: AlertService,
        classifier: SafetyClassifier,
    ) -> None:
        self._db = db
        self._clock = clock
        self._people = people
        self._alerts = alerts
        self._classifier = classifier

    def log(self, person_id: int, note: str = "", mood: int | str | None = None) -> CheckinResult:
        person = self._people.get(person_id)
        note = (note or "").strip()[:MAX_NOTE]
        mood_value = parse_mood(mood)
        assessment = self._classifier.assess(note)
        now = self._clock.now()
        first_today = not self.has_checked_in_today(person_id)
        with self._db.transaction():
            checkin_id = self._db.insert(
                "INSERT INTO checkins (person_id, ts, note, mood, severity) VALUES (?, ?, ?, ?, ?)",
                (person_id, to_iso(now), note, mood_value, int(assessment.severity)),
            )
            alert = None
            if assessment.concerning:
                alert = self._alerts.raise_alert(
                    person_id,
                    assessment.severity,
                    AlertKind.SAFETY,
                    f"{person.name} said: \u201c{note}\u201d (detected: {assessment.describe()})",
                )
        row = self._db.one("SELECT * FROM checkins WHERE id = ?", (checkin_id,))
        return CheckinResult(Checkin.from_row(row), assessment, alert, first_today)

    def for_day(self, person_id: int, day) -> list[Checkin]:
        zone = get_zone(self._people.get(person_id).timezone)
        start, end = local_day_bounds(day, zone)
        rows = self._db.all(
            "SELECT * FROM checkins WHERE person_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (person_id, to_iso(start), to_iso(end)),
        )
        return [Checkin.from_row(r) for r in rows]

    def has_checked_in_today(self, person_id: int) -> bool:
        zone = get_zone(self._people.get(person_id).timezone)
        return bool(self.for_day(person_id, local_date(self._clock.now(), zone)))

    def last(self, person_id: int) -> Checkin | None:
        row = self._db.one(
            "SELECT * FROM checkins WHERE person_id = ? ORDER BY ts DESC, id DESC LIMIT 1",
            (person_id,),
        )
        return Checkin.from_row(row) if row else None
