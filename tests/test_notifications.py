from __future__ import annotations

import json
import logging

import httpx
import pytest

from carecircle.llm import LLMClient, LLMSecondOpinion
from carecircle.models import Severity
from carecircle.notifier import (
    BotCommands, ConsoleNotifier, RecordingNotifier, TelegramClient, TelegramNotifier, TelegramPoller,
)
from carecircle.safety import SafetyClassifier


def tg_client(handler) -> TelegramClient:
    return TelegramClient("123:SECRET", httpx.Client(transport=httpx.MockTransport(handler)))


# ---------------------------------------------------------------- telegram transport
def test_send_message_success_and_failure():
    seen = []

    def ok(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    assert tg_client(ok).send_message("42", "hello")
    assert seen == [{"chat_id": "42", "text": "hello"}]
    assert not tg_client(lambda r: httpx.Response(403, json={})).send_message("42", "x")

    def boom(request):
        raise httpx.ConnectError("down")

    assert not tg_client(boom).send_message("42", "x")


def test_message_is_truncated_to_telegram_limit():
    sent = []
    tg_client(lambda r: sent.append(json.loads(r.content)) or httpx.Response(200, json={})).send_message("1", "x" * 9000)
    assert len(sent[0]["text"]) == 4000


def test_token_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    tg_client(lambda r: httpx.Response(500, json={})).send_message("1", "x")
    assert "SECRET" not in caplog.text


def test_notifier_needs_chat_id(family, svc):
    amma, rahul, _ = family
    notifier = TelegramNotifier(tg_client(lambda r: httpx.Response(200, json={})))
    assert not notifier.send(svc.people.get(rahul.id), "hi")  # no chat linked
    linked = svc.people.set_telegram_chat(rahul.id, "99")
    assert notifier.send(linked, "hi")


def test_console_and_recording_notifiers(family, caplog):
    _, rahul, _ = family
    caplog.set_level(logging.INFO)
    assert ConsoleNotifier().send(rahul, "line1\nline2")
    assert "line1 | line2" in caplog.text
    assert not RecordingNotifier(deliverable=False).send(rahul, "x")


# ---------------------------------------------------------------- bot commands
def test_bot_start_unlinked_and_linked(svc, family):
    amma, rahul, _ = family
    bot = BotCommands(svc)
    assert "carecircle link-telegram" in bot.handle("555", "/start")
    assert bot.handle("555", "hello there") is None
    svc.people.set_telegram_chat(rahul.id, "555")
    assert "Hi Rahul" in bot.handle("555", "/start")
    assert "/ack" in bot.handle("555", "/help@CareCircleBot")


def test_bot_status_and_ack(svc, family):
    amma, rahul, priya = family
    svc.people.set_telegram_chat(rahul.id, "555")
    bot = BotCommands(svc)
    assert "Amma has not checked in" in bot.handle("555", "/status")
    alert = svc.checkins.log(amma.id, "I fell").alert.alert
    assert "Usage" in bot.handle("555", "/ack")
    assert "marked as handled" in bot.handle("555", f"/ack {alert.id}")
    assert svc.alerts.get(alert.id).acknowledged_at is not None
    assert "Sorry" in bot.handle("555", "/ack 9999")
    assert "Unknown command" in bot.handle("555", "/frobnicate")
    assert "isn't linked" in bot.handle("777", "/status")


def test_bot_ack_rejects_outsiders(svc, family):
    from carecircle.models import Role

    amma, rahul, _ = family
    svc.people.create("Stranger", Role.CAREGIVER, telegram_chat_id="888")
    alert = svc.checkins.log(amma.id, "I fell").alert.alert
    assert "isn't for someone in your circle" in BotCommands(svc).handle("888", f"/ack {alert.id}")
    assert svc.alerts.get(alert.id).acknowledged_at is None


def test_poller_handles_updates_and_advances_offset(svc, family):
    amma, rahul, _ = family
    svc.people.set_telegram_chat(rahul.id, "555")
    replies, offsets = [], []

    def handler(request):
        if request.url.path.endswith("getUpdates"):
            offsets.append(request.url.params.get("offset"))
            return httpx.Response(200, json={"result": [
                {"update_id": 10, "message": {"chat": {"id": 555}, "text": "/status"}},
                {"update_id": 11, "message": {"chat": {"id": 555}, "text": "just chatting"}},
                {"update_id": 12},
            ]})
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={})

    poller = TelegramPoller(tg_client(handler), BotCommands(svc))
    assert poller.poll_once(timeout=0) == 1
    poller.poll_once(timeout=0)
    assert offsets == [None, "13"] and replies[0]["chat_id"] == "555"
    poller.stop()


# ---------------------------------------------------------------- LLM second opinion
def llm_client(content: str, status: int = 200) -> LLMClient:
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "m" and request.headers["authorization"] == "Bearer k"
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})

    return LLMClient("http://llm.test/v1/", "m", "k", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_llm_raises_severity_beyond_rules():
    clf = SafetyClassifier(second_opinion=LLMSecondOpinion(llm_client('{"severity": "urgent", "category": "Stroke"}')))
    result = clf.assess("my words are coming out jumbled and my smile is lopsided")
    assert result.severity is Severity.URGENT and "llm:stroke" in result.categories


@pytest.mark.parametrize("content", ["not json", '{"severity": "banana"}', '{"severity": "info"}', ""])
def test_llm_garbage_or_info_changes_nothing(content):
    clf = SafetyClassifier(second_opinion=LLMSecondOpinion(llm_client(content)))
    assert clf.assess("lovely weather").severity is Severity.INFO


def test_llm_http_error_never_hides_rule_hit():
    clf = SafetyClassifier(second_opinion=LLMSecondOpinion(llm_client("{}", status=500)))
    assert clf.assess("I feel dizzy").severity is Severity.ATTENTION


def test_llm_not_called_when_rules_already_urgent():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = LLMClient("http://x/v1", "m", http=httpx.Client(transport=httpx.MockTransport(handler)))
    SafetyClassifier(second_opinion=LLMSecondOpinion(client)).assess("I fell down")
    assert calls == []


def test_llm_from_settings_requires_config():
    from carecircle.config import Settings

    assert LLMClient.from_settings(Settings()) is None
    assert LLMClient.from_settings(Settings(llm_base_url="http://x/v1", llm_model="m")) is not None
