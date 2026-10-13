import pytest

from carecircle.errors import Ambiguous, NotFound, ValidationError
from carecircle.models import Role


def test_create_and_find(svc, family):
    amma, rahul, priya = family
    assert svc.people.find("amma").id == amma.id
    assert svc.people.find(str(rahul.id)).name == "Rahul"
    assert svc.people.find("pri").id == priya.id


def test_duplicate_name_rejected(svc, family):
    with pytest.raises(ValidationError):
        svc.people.create("AMMA", Role.FAMILY)


def test_find_errors(svc, family):
    svc.people.create("Rahul Sr", Role.FAMILY)
    with pytest.raises(Ambiguous) as exc:
        svc.people.find("rahu")
    assert set(exc.value.options) == {"Rahul", "Rahul Sr"}
    with pytest.raises(NotFound):
        svc.people.find("Nobody")


def test_invalid_timezone(svc):
    with pytest.raises(ValidationError):
        svc.people.create("X", Role.ELDER, timezone="Mars/Olympus")


def test_link_rules(svc, family):
    amma, rahul, _ = family
    with pytest.raises(ValidationError):
        svc.people.link(rahul.id, amma.id)  # rahul is not an elder
    other = svc.people.create("Dadi", Role.ELDER)
    with pytest.raises(ValidationError):
        svc.people.link(amma.id, other.id)  # elder as member


def test_circle_queries(svc, family):
    amma, rahul, priya = family
    assert [p.name for p in svc.people.caregivers_of(amma.id)] == ["Rahul"]
    assert {p.name for p in svc.people.members_of(amma.id)} == {"Rahul", "Priya"}
    assert [p.name for p in svc.people.elders_of(rahul.id)] == ["Amma"]
    assert svc.people.relation(amma.id, rahul.id) == "son"
    assert svc.people.connected(rahul.id, priya.id)
    stranger = svc.people.create("Stranger", Role.FAMILY)
    assert not svc.people.connected(stranger.id, amma.id)
