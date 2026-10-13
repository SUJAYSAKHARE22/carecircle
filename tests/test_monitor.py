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
