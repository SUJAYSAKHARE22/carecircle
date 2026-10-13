import pytest

from carecircle.errors import ValidationError
from carecircle.models import ReminderStatus, Role


def test_message_roundtrip_read_once(svc, family):
    amma, rahul, _ = family
    svc.messages.send(rahul.id, amma.id, "I'll call at 7")
    inbox = svc.messages.take_inbox(amma.id)
    assert [m.body for m in inbox] == ["I'll call at 7"]
    assert svc.messages.take_inbox(amma.id) == []


def test_message_validation(svc, family):
    amma, rahul, _ = family
    stranger = svc.people.create("Stranger", Role.FAMILY)
    with pytest.raises(ValidationError):
        svc.messages.send(rahul.id, amma.id, "   ")
    with pytest.raises(ValidationError):
        svc.messages.send(rahul.id, amma.id, "x" * 501)
    with pytest.raises(ValidationError):
        svc.messages.send(stranger.id, amma.id, "hi")


def test_summary_text_and_dict(svc, family, clock):
    amma, rahul, _ = family
    svc.checkins.log(amma.id, "Good morning", mood=4)
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    svc.reminders.create(amma.id, "Vitamin D", "08:30")
    clock.advance(minutes=40)
    svc.reminders.respond(amma.id, ReminderStatus.TAKEN, "BP tablet")
    svc.checkins.log(amma.id, "feeling dizzy")
    svc.messages.send(rahul.id, amma.id, "Call at 7")
    summary = svc.summaries.build(amma.id)
    data = summary.to_dict()
    assert data["checked_in"] and data["first_checkin"] == "7:30 AM"
    assert data["reminders"]["taken"] == 1 and data["reminders"]["total"] == 2
    assert data["concerns"][0]["severity"] == "attention"
    assert data["messages"] == {"received": 1, "sent": 0}
    assert "1 of 2 confirmed" in data["text"] and "1 concern noted" in data["text"]


def test_summary_when_silent(svc, family):
    amma, *_ = family
    text = svc.summaries.build(amma.id).to_text()
    assert "has not checked in" in text and "No concerns noted" in text
