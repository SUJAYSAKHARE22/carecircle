from datetime import timedelta

import pytest

from carecircle.errors import ValidationError
from carecircle.models import AlertKind, Severity
from carecircle.services.checkins import parse_mood


def test_plain_checkin_has_no_alert(svc, family):
    amma, *_ = family
    result = svc.checkins.log(amma.id, "Good morning, had my tea", mood="good")
    assert result.first_today and result.alert is None
    assert result.checkin.mood == 4
    assert svc.checkins.has_checked_in_today(amma.id)
    assert not svc.checkins.log(amma.id, "again").first_today


def test_concerning_checkin_raises_alert(svc, family):
    amma, rahul, _ = family
    result = svc.checkins.log(amma.id, "I feel dizzy")
    assert result.alert and result.alert.created
    assert result.alert.alert.severity == Severity.ATTENTION
    assert result.alert.alert.kind == AlertKind.SAFETY
    assert [p.name for p in svc.alerts.recipients(result.alert.alert)] == ["Rahul"]


def test_alert_dedupe_and_escalation(svc, family, clock):
    amma, *_ = family
    first = svc.checkins.log(amma.id, "I feel dizzy").alert
    again = svc.checkins.log(amma.id, "still dizzy").alert
    assert not again.created and again.alert.id == first.alert.id
    urgent = svc.checkins.log(amma.id, "I fell down").alert
    assert urgent.created and urgent.alert.severity == Severity.URGENT
    clock.advance(minutes=31)
    later = svc.checkins.log(amma.id, "dizzy again").alert
    assert later.created


def test_recipients_fall_back_to_family(svc):
    from carecircle.models import Role

    amma = svc.people.create("Amma", Role.ELDER)
    priya = svc.people.create("Priya", Role.FAMILY)
    svc.people.link(amma.id, priya.id)
    alert = svc.checkins.log(amma.id, "I fell").alert.alert
    assert [p.name for p in svc.alerts.recipients(alert)] == ["Priya"]


def test_notify_and_acknowledge(svc, family):
    amma, *_ = family
    alert = svc.checkins.log(amma.id, "chest pain").alert.alert
    assert [a.id for a in svc.alerts.unnotified()] == [alert.id]
    svc.alerts.mark_notified(alert.id)
    assert svc.alerts.unnotified() == []
    assert svc.alerts.acknowledge(alert.id).acknowledged_at is not None


def test_note_is_truncated(svc, family):
    amma, *_ = family
    assert len(svc.checkins.log(amma.id, "a" * 5000).checkin.note) == 600


@pytest.mark.parametrize(
    "raw, expected",
    [(3, 3), ("4", 4), ("Good", 4), ("terrible", 1), (None, None), ("", None)],
)
def test_parse_mood(raw, expected):
    assert parse_mood(raw) == expected


@pytest.mark.parametrize("raw", [0, 6, "meh", True])
def test_parse_mood_invalid(raw):
    with pytest.raises(ValidationError):
        parse_mood(raw)
