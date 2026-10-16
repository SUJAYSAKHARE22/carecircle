from datetime import timedelta

import pytest

from carecircle import i18n
from carecircle.clock import FixedClock, OffsetClock
from carecircle.config import Settings
from carecircle.demo import seed_demo
from carecircle.errors import ValidationError


def test_every_message_has_all_languages():
    assert i18n.missing_translations() == {}


@pytest.mark.parametrize("key", i18n.keys())
@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_templates_format_cleanly(key, lang):
    text = i18n.t(lang, key, name="Amma", who="Rahul", n=2, items="a, b", sender="Rahul", body="hi",
                  item="tablet", options="a, b", to="Rahul")
    assert text and "{" not in text


def test_language_fallback_and_joining():
    assert i18n.normalize_language("hi-IN") == "hi"
    assert i18n.normalize_language("fr") == "en"
    assert i18n.normalize_language(None) == "en"
    assert i18n.join_names("en", []) == "your family"
    assert i18n.join_names("en", ["A", "B"]) == "A and B"
    assert i18n.join_names("en", ["A", "B", "C"]) == "A, B and C"


def test_offset_clock_moves_and_resets():
    clock = OffsetClock()
    before = clock.now()
    clock.advance(hours=2)
    assert clock.now() - before >= timedelta(hours=2)
    clock.reset()
    assert clock.offset == timedelta(0)


def test_fixed_clock_requires_tz():
    from datetime import datetime

    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))


def test_seed_demo_is_idempotent(svc):
    first = seed_demo(svc)
    again = seed_demo(svc)
    assert first == again == {"elder": "Amma", "caregiver": "Rahul", "family": "Priya"}
    amma = svc.people.find("Amma")
    assert len(svc.people.list()) == 3 and len(svc.reminders.list(amma.id)) == 3
    assert svc.people.relation(amma.id, svc.people.find("Rahul").id) == "son"


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CARECIRCLE_DB", str(tmp_path / "x" / "cc.db"))
    monkeypatch.setenv("CARECIRCLE_DEMO", "yes")
    monkeypatch.setenv("CARECIRCLE_DIGEST_TIME", "21:30")
    monkeypatch.setenv("CARECIRCLE_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("CARECIRCLE_LLM_MODEL", "llama3")
    monkeypatch.setenv("CARECIRCLE_ALLOWED_HOSTS", "a.example.com, b.example.com")
    s = Settings.from_env()
    assert s.demo_mode and s.llm_configured and (tmp_path / "x").is_dir()
    assert s.digest_time.hour == 21 and s.allowed_hosts == ("a.example.com", "b.example.com")


@pytest.mark.parametrize("name, value", [("CARECIRCLE_PORT", "abc"), ("CARECIRCLE_GRACE_MINUTES", "-1"), ("CARECIRCLE_TIMEZONE", "Mars/X")])
def test_settings_reject_bad_values(monkeypatch, name, value):
    monkeypatch.setenv("CARECIRCLE_DB", ":memory:")
    monkeypatch.setenv(name, value)
    with pytest.raises((ValueError, ValidationError)):
        Settings.from_env()


def test_database_migrates_and_rolls_back(tmp_path):
    from carecircle.db import SCHEMA_VERSION, Database

    db = Database(tmp_path / "t.db")
    assert db.one("PRAGMA user_version")[0] == SCHEMA_VERSION
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.insert("INSERT INTO people (name, role, timezone, created_at) VALUES ('X','elder','UTC','t')")
            raise RuntimeError("boom")
    assert db.one("SELECT COUNT(*) c FROM people")["c"] == 0
    with db.transaction():
        with db.transaction():  # re-entrant
            db.insert("INSERT INTO people (name, role, timezone, created_at) VALUES ('Y','elder','UTC','t')")
    assert db.one("SELECT COUNT(*) c FROM people")["c"] == 1
    db.close()
    assert Database(tmp_path / "t.db").one("SELECT COUNT(*) c FROM people")["c"] == 1  # persisted
