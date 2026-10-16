
from carecircle.notifier import RecordingNotifier
from carecircle.scheduler import Scheduler
from carecircle.services.dispatcher import DispatchReport


def test_urgent_checkin_notifies_caregiver_immediately(notified):
    svc, notifier = notified
    amma = svc.people.find("Amma")
    alert = svc.checkins.log(amma.id, "I fell in the bathroom").alert.alert
    assert [name for name, _ in notifier.sent] == ["Rahul"]
    text = notifier.sent[0][1]
    assert "URGENT" in text and f"/ack {alert.id}" in text and "fell" in text
    assert svc.alerts.get(alert.id).notified_at is not None


def test_deduped_alert_does_not_notify_twice(notified):
    svc, notifier = notified
    amma = svc.people.find("Amma")
    svc.checkins.log(amma.id, "I feel dizzy")
    svc.checkins.log(amma.id, "still dizzy")
    assert len(notifier.sent) == 1


def test_undeliverable_alert_stays_pending_then_retries(clock):
    from carecircle.config import Settings
    from carecircle.db import Database
    from carecircle.models import Role
    from carecircle.services import build_services

    notifier = RecordingNotifier(deliverable=False)
    svc = build_services(Settings(db_path=":memory:"), db=Database(":memory:"), clock=clock, notifier=notifier)
    amma = svc.people.create("Amma", Role.ELDER)
    rahul = svc.people.create("Rahul", Role.CAREGIVER)
    svc.people.link(amma.id, rahul.id)
    alert = svc.checkins.log(amma.id, "chest pain").alert.alert
    assert [a.id for a in svc.alerts.unnotified()] == [alert.id]
    report = svc.dispatcher.dispatch(svc.monitor.run())
    assert report.alerts_pending == 1 and report.alerts_sent == 0
    notifier.deliverable = True
    assert svc.dispatcher.flush_alerts() == 1
    assert svc.alerts.unnotified() == []


def test_caregiver_messages_are_forwarded_once(notified):
    svc, notifier = notified
    amma, rahul = svc.people.find("Amma"), svc.people.find("Rahul")
    svc.messages.send(amma.id, rahul.id, "Please bring milk")
    assert svc.dispatcher.dispatch(svc.monitor.run()).messages_sent == 1
    assert svc.dispatcher.dispatch(svc.monitor.run()).messages_sent == 0
    assert "Message from Amma" in notifier.sent[-1][1] and "milk" in notifier.sent[-1][1]


def test_elder_messages_are_not_pushed(notified):
    svc, notifier = notified
    amma, rahul = svc.people.find("Amma"), svc.people.find("Rahul")
    svc.messages.send(rahul.id, amma.id, "Call at 7")
    assert svc.dispatcher.dispatch(svc.monitor.run()).messages_sent == 0
    assert len(svc.messages.unread_for(amma.id)) == 1  # waits for the elder to ask


def test_daily_digest_sent_once_after_digest_time(notified, clock):
    svc, notifier = notified
    amma = svc.people.find("Amma")
    svc.checkins.log(amma.id, "morning", mood=4)
    assert svc.dispatcher.dispatch(svc.monitor.run()).digests_sent == 0  # 07:30 local
    clock.advance(hours=13)  # 20:30 local
    assert svc.dispatcher.dispatch(svc.monitor.run()).digests_sent == 1
    assert svc.dispatcher.dispatch(svc.monitor.run()).digests_sent == 0
    digest = [t for _, t in notifier.sent if "Daily summary" in t]
    assert len(digest) == 1 and "Amma first checked in" in digest[0]
    clock.advance(days=1)  # next day: new digest
    assert svc.dispatcher.dispatch(svc.monitor.run()).digests_sent == 1


def test_nudge_goes_to_elder_in_their_language(notified, clock):
    svc, notifier = notified
    svc.people.set_telegram_chat(svc.people.find("Amma").id, "222")
    clock.advance(hours=2.6)  # 10:06 local, inside grace
    report = svc.dispatcher.dispatch(svc.monitor.run())
    assert report.nudges_sent == 1
    assert [n for n, t in notifier.sent if n == "Amma" and "सुप्रभात" in t]


def test_missed_checkin_end_to_end(notified, clock):
    svc, notifier = notified
    clock.advance(hours=4)  # 11:30 local, past grace
    svc.dispatcher.dispatch(svc.monitor.run())
    # delivered the moment the monitor raised it; the sweep has nothing left to do
    assert [t for n, t in notifier.sent if n == "Rahul" and "has not checked in" in t]
    assert svc.alerts.unnotified() == []


def test_missed_reminder_end_to_end(notified, clock):
    svc, notifier = notified
    amma = svc.people.find("Amma")
    svc.checkins.log(amma.id, "morning")
    svc.reminders.create(amma.id, "BP tablet", "08:00")
    clock.advance(minutes=130)
    svc.dispatcher.dispatch(svc.monitor.run())
    assert any("did not confirm" in t for _, t in notifier.sent)


def test_listener_failure_never_loses_alert(clock):
    from carecircle.config import Settings
    from carecircle.db import Database
    from carecircle.models import Role
    from carecircle.services import build_services

    svc = build_services(Settings(db_path=":memory:"), db=Database(":memory:"), clock=clock)
    amma = svc.people.create("Amma", Role.ELDER)
    svc.alerts.add_listener(lambda alert: (_ for _ in ()).throw(RuntimeError("boom")))
    raised = svc.checkins.log(amma.id, "I fell").alert
    assert raised.created and svc.alerts.get(raised.alert.id)


def test_scheduler_tick_and_thread(notified, monkeypatch):
    svc, _ = notified
    scheduler = Scheduler(svc, interval_seconds=0.01)
    assert isinstance(scheduler.tick(), DispatchReport)
    ticks = []
    monkeypatch.setattr(scheduler, "tick", lambda: ticks.append(1) or (_ for _ in ()).throw(RuntimeError("x")))
    scheduler.start()
    import time

    deadline = time.time() + 2
    while len(ticks) < 3 and time.time() < deadline:
        time.sleep(0.01)
    scheduler.stop()
    assert len(ticks) >= 3  # survived exceptions and kept ticking
