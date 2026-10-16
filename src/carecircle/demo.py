"""Demo data: a believable family so the simulator and dashboard are alive on first launch."""

from __future__ import annotations

from .models import Role
from .services import Services

DEMO_ELDER = "Amma"


def seed_demo(services: Services, *, telegram_chat_id: str | None = None) -> dict[str, str]:
    """Idempotently create Amma (Hindi-speaking), her son Rahul, daughter Priya, and routines."""
    people = services.people
    existing = {p.name.casefold(): p for p in people.list()}

    def ensure(name: str, role: Role, **kwargs):
        return existing.get(name.casefold()) or people.create(name, role, **kwargs)

    amma = ensure(DEMO_ELDER, Role.ELDER, language="hi")
    rahul = ensure("Rahul", Role.CAREGIVER, telegram_chat_id=telegram_chat_id)
    priya = ensure("Priya", Role.FAMILY)
    people.link(amma.id, rahul.id, "son")
    people.link(amma.id, priya.id, "daughter")

    if not services.reminders.list(amma.id):
        services.reminders.create(amma.id, "Blood pressure tablet", "08:00", created_by=rahul.id)
        services.reminders.create(amma.id, "Vitamin D", "13:00", created_by=rahul.id)
        services.reminders.create(amma.id, "Evening walk", "18:00", created_by=priya.id)
    return {"elder": amma.name, "caregiver": rahul.name, "family": priya.name}
