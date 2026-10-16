from carecircle.models import AlertKind, ReminderStatus


def test_quiet_before_deadline(svc, family):
    report = svc.monitor.run()
    assert report.nudges == () and report.alerts == ()


def test_nudge_then_alert_once(svc, family, clock):
    amma, *_ = family
    clock.advance(hours=2.6)  # 10:06 local
    first = svc.monitor.run()
    assert [n.person_id for n in first.nudges] == [amma.id]
    assert svc.monitor.run().nudges == ()  # nudged only once per day
    clock.advance(hours=1)  # 11:06 local, past 60 min grace
    report = svc.monitor.run()
    assert [a.alert.kind for a in report.alerts] == [AlertKind.MISSED_CHECKIN]
    assert report.alerts[0].created
    assert not svc.monitor.run().alerts[0].created  # one per day


def test_checkin_silences_monitor(svc, family, clock):
    amma, *_ = family
    svc.checkins.log(amma.id, "up and about")
    clock.advance(hours=4)
    report = svc.monitor.run()
    assert report.nudges == () and report.alerts == ()


def test_missed_reminder_alert(svc, family, clock):
    amma, *_ = family
    svc.checkins.log(amma.id, "morning")
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    clock.advance(minutes=130)  # 09:40 local
    report = svc.monitor.run()
    assert [e.title for e in report.missed_events] == ["BP tablet"]
    assert report.alerts[0].alert.kind is AlertKind.MISSED_REMINDER
    assert svc.monitor.run().alerts == ()


def test_confirmed_reminder_is_not_missed(svc, family, clock):
    amma, *_ = family
    svc.checkins.log(amma.id, "morning")
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    clock.advance(minutes=40)
    svc.reminders.respond(amma.id, ReminderStatus.TAKEN)
    clock.advance(minutes=120)
    assert svc.monitor.run().missed_events == ()


def test_late_setup_does_not_create_instant_missed_alerts(clock):
    """Regression: onboarding in the evening must not alert about the morning that already passed."""
    from carecircle.config import Settings
    from carecircle.db import Database
    from carecircle.models import Role
    from carecircle.notifier import RecordingNotifier
    from carecircle.services import build_services

    clock.advance(hours=13)  # 20:30 local, long after the 10:00 deadline and 08:00 dose
    notifier = RecordingNotifier()
    svc = build_services(Settings(db_path=":memory:"), db=Database(":memory:"), clock=clock, notifier=notifier)
    amma = svc.people.create("Amma", Role.ELDER)
    rahul = svc.people.create("Rahul", Role.CAREGIVER)
    svc.people.link(amma.id, rahul.id)
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    svc.reminders.create(amma.id, "Evening walk", "21:00")

    report = svc.monitor.run()
    assert report.alerts == () and report.missed_events == () and report.nudges == ()
    assert [e.title for e in svc.reminders.events_for_day(amma.id, clock.now().date())] == ["Evening walk"]
    assert svc.monitor.checkin_statuses()[0].state == "ok"

    clock.advance(hours=1)  # 21:30: the walk is genuinely owed now but still inside its grace period
    assert svc.monitor.run().alerts == ()
    clock.advance(hours=1)  # 22:30: past grace -> a real miss
    assert [e.title for e in svc.monitor.run().missed_events] == ["Evening walk"]

    clock.advance(hours=11.5)  # next day 10:00 local+: a real missed check-in
    clock.advance(hours=1.5)
    kinds = {a.alert.kind.value for a in svc.monitor.run().alerts}
    assert "missed_checkin" in kinds
