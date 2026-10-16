from __future__ import annotations

from datetime import datetime, timezone

import pytest

from carecircle.clock import FixedClock
from carecircle.config import Settings
from carecircle.db import Database
from carecircle.models import Role
from carecircle.services import Services, build_services

# Wednesday 14 Oct 2026, 07:30 in Asia/Kolkata
START = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def svc(clock: FixedClock) -> Services:
    settings = Settings(db_path=":memory:")
    return build_services(settings, db=Database(":memory:"), clock=clock)


@pytest.fixture
def family(svc: Services):
    """Amma (elder) with son Rahul (caregiver) and daughter Priya (family)."""
    amma = svc.people.create("Amma", Role.ELDER, language="hi")
    rahul = svc.people.create("Rahul", Role.CAREGIVER)
    priya = svc.people.create("Priya", Role.FAMILY)
    svc.people.link(amma.id, rahul.id, "son")
    svc.people.link(amma.id, priya.id, "daughter")
    return amma, rahul, priya


@pytest.fixture
def notified(clock: FixedClock):
    """Services wired to a RecordingNotifier so deliveries can be asserted."""
    from carecircle.notifier import RecordingNotifier

    notifier = RecordingNotifier()
    services = build_services(
        Settings(db_path=":memory:"), db=Database(":memory:"), clock=clock, notifier=notifier
    )
    amma = services.people.create("Amma", Role.ELDER, language="hi")
    rahul = services.people.create("Rahul", Role.CAREGIVER, telegram_chat_id="111")
    priya = services.people.create("Priya", Role.FAMILY)
    services.people.link(amma.id, rahul.id, "son")
    services.people.link(amma.id, priya.id, "daughter")
    return services, notifier
