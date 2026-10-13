import pytest

from carecircle.errors import Ambiguous, NotFound, ValidationError
from carecircle.models import ReminderStatus


def test_create_validates(svc, family):
    amma, *_ = family
    with pytest.raises(ValidationError):
        svc.reminders.create(amma.id, "", "08:00")
    with pytest.raises(ValidationError):
        svc.reminders.create(amma.id, "Tablet", "25:00")
    with pytest.raises(ValidationError):
        svc.reminders.create(amma.id, "Tablet", "08:00", days=[7])


def test_events_materialize_once_per_day(svc, family):
    amma, *_ = family
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    svc.reminders.create(amma.id, "Evening walk", "18:00", days=[0])  # Monday only; today is Wed
    assert svc.reminders.materialize(amma.id, svc.clock.now().date()) == 0
    events = svc.reminders.events_for_day(amma.id, svc.clock.now().date())
    assert [e.title for e in events] == ["BP tablet"]


def test_due_window(svc, family, clock):
    amma, *_ = family
    svc.reminders.create(amma.id, "BP tablet", "08:00")  # 07:30 local now
    assert svc.reminders.due_events(amma.id, lookahead_minutes=15) == []
    assert [e.title for e in svc.reminders.due_events(amma.id, lookahead_minutes=30)] == ["BP tablet"]


def test_respond_single_and_hint(svc, family, clock):
    amma, *_ = family
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    svc.reminders.create(amma.id, "Vitamin D", "08:00")
    clock.advance(minutes=40)
    with pytest.raises(Ambiguous) as exc:
        svc.reminders.respond(amma.id, "taken")
    assert set(exc.value.options) == {"BP tablet", "Vitamin D"}
    event = svc.reminders.respond(amma.id, ReminderStatus.TAKEN, "my blood pressure tablet")
    assert event.title == "BP tablet" and event.status is ReminderStatus.TAKEN
    only = svc.reminders.respond(amma.id, "skipped")
    assert only.title == "Vitamin D" and only.status is ReminderStatus.SKIPPED
    with pytest.raises(NotFound):
        svc.reminders.respond(amma.id, "taken")


def test_respond_rejects_bad_status_and_unmatched_hint(svc, family, clock):
    amma, *_ = family
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    clock.advance(minutes=40)
    with pytest.raises(ValidationError):
        svc.reminders.respond(amma.id, "missed")
    with pytest.raises(NotFound):
        svc.reminders.respond(amma.id, "taken", "zzzz")


def test_mark_overdue(svc, family, clock):
    amma, *_ = family
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    clock.advance(minutes=40)  # 08:10 local
    assert svc.reminders.mark_overdue(45) == []
    clock.advance(minutes=40)  # 08:50 local
    missed = svc.reminders.mark_overdue(45)
    assert [e.status for e in missed] == [ReminderStatus.MISSED]
    assert svc.reminders.mark_overdue(45) == []  # idempotent


def test_deactivate_removes_future_events(svc, family):
    amma, *_ = family
    reminder = svc.reminders.create(amma.id, "BP tablet", "08:00")
    svc.reminders.deactivate(reminder.id)
    assert svc.reminders.list(amma.id) == []
    assert svc.reminders.events_for_day(amma.id, svc.clock.now().date()) == []
