"""The simulator agent, exercised through genuine MCP client sessions."""

from __future__ import annotations

import pytest

from carecircle.agent import Simulator, extract_message, resolve_recipient
from carecircle.server import build_server


@pytest.fixture
def sim(svc, family):
    return Simulator(svc, build_server(svc))


def names(result):
    return [c.name for c in result.tool_calls]


async def test_plain_checkin_english(sim):
    r = await sim.turn("Amma", "Good morning, I feel fine", "en")
    assert names(r) == ["log_checkin"] and r.reply.startswith("Good morning, Amma")
    assert r.tool_calls[0].arguments["mood"] == 4
    assert r.to_dict()["speech_lang"] == "en-IN"


async def test_defaults_to_the_elders_language(sim):
    r = await sim.turn(None, "namaste")  # Amma speaks Hindi
    assert r.language == "hi" and "सुप्रभात" in r.reply and r.to_dict()["speech_lang"] == "hi-IN"


@pytest.mark.parametrize(
    "text, lang, needle",
    [("I fell down in the bathroom", "en", "alerted Rahul"),
     ("मैं गिर गई", "hi", "Rahul"),
     ("मी पडले", "mr", "Rahul")],
)
async def test_urgent_phrases_alert_family(sim, svc, text, lang, needle):
    r = await sim.turn("Amma", text, lang)
    assert r.tool_calls[0].result["concern_level"] == "urgent" and needle in r.reply
    assert svc.alerts.list_for(svc.people.find("Amma").id)[0].severity.label == "urgent"


async def test_attention_phrase(sim):
    r = await sim.turn("Amma", "I feel dizzy", "en")
    assert r.tool_calls[0].result["concern_level"] == "attention" and "told Rahul" in r.reply


async def test_reminders_are_read_after_checkin(sim, svc, clock):
    amma = svc.people.find("Amma")
    svc.reminders.create(amma.id, "Blood pressure tablet", "08:00")
    clock.advance(minutes=30)
    r = await sim.turn("Amma", "good morning", "en")
    assert names(r) == ["log_checkin", "get_pending_items"]
    assert "Blood pressure tablet" in r.reply and "1 reminder" in r.reply


async def test_confirm_single_reminder(sim, svc, clock):
    amma = svc.people.find("Amma")
    svc.reminders.create(amma.id, "Blood pressure tablet", "08:00")
    clock.advance(minutes=30)
    r = await sim.turn("Amma", "I took my tablet", "en")
    assert names(r) == ["confirm_reminder"] and "marked Blood pressure tablet as taken" in r.reply


async def test_confirm_with_hint_disambiguates(sim, svc, clock):
    amma = svc.people.find("Amma")
    svc.reminders.create(amma.id, "Blood pressure tablet", "08:00")
    svc.reminders.create(amma.id, "Vitamin D tablet", "08:00")
    clock.advance(minutes=30)
    ask = await sim.turn("Amma", "I took my tablet", "en")
    assert "Which one" in ask.reply and "Vitamin D tablet" in ask.reply
    done = await sim.turn("Amma", "I took my blood pressure tablet", "en")
    assert done.tool_calls[0].arguments["reminder"] == "blood pressure"
    assert "Blood pressure tablet as taken" in done.reply


async def test_skipped_and_nothing_to_confirm(sim, svc, clock):
    amma = svc.people.find("Amma")
    nothing = await sim.turn("Amma", "I took my tablet", "en")
    assert "nothing waiting" in nothing.reply.lower() or "don't see anything" in nothing.reply
    svc.reminders.create(amma.id, "Vitamin D", "08:00")
    clock.advance(minutes=30)
    skipped = await sim.turn("Amma", "I didn't take my vitamin", "en")
    assert skipped.tool_calls[0].arguments["status"] == "skipped" and "skipped Vitamin D" in skipped.reply


async def test_hindi_confirmation(sim, svc, clock):
    amma = svc.people.find("Amma")
    svc.reminders.create(amma.id, "दवाई", "08:00")
    clock.advance(minutes=30)
    r = await sim.turn("Amma", "मैंने दवाई ले ली", "hi")
    assert names(r) == ["confirm_reminder"] and "दर्ज कर दिया" in r.reply


@pytest.mark.parametrize(
    "text, body",
    [("tell Rahul that I took my tablets", "I took my tablets"),
     ("tell my son to call me", "call me"),
     ("Rahul ko bol do ki main theek hoon", "main theek hoon"),
     ("message my daughter I'm fine", "I'm fine")],
)
async def test_message_routing(sim, svc, text, body):
    r = await sim.turn("Amma", text, "en")
    assert names(r) == ["leave_message"] and r.tool_calls[0].arguments["message"] == body
    assert "Done" in r.reply


async def test_message_without_recipient_asks_who(sim):
    r = await sim.turn("Amma", "please tell them I'm hungry", "en")
    assert r.tool_calls == [] and "Who should I send it to" in r.reply


async def test_read_messages(sim, svc):
    amma, rahul = svc.people.find("Amma"), svc.people.find("Rahul")
    svc.messages.send(rahul.id, amma.id, "I'll call at 7")
    r = await sim.turn("Amma", "Do I have any messages?", "en")
    assert names(r) == ["get_pending_items"] and "Rahul says: I'll call at 7" in r.reply
    again = await sim.turn("Amma", "Do I have any messages?", "en")
    assert "Nothing is waiting" in again.reply


async def test_input_validation(sim):
    with pytest.raises(ValueError):
        await sim.turn("Amma", "   ")
    with pytest.raises(ValueError):
        await sim.turn("Amma", "x" * 601)


async def test_multiple_elders_need_a_name(svc, family):
    from carecircle.models import Role

    svc.people.create("Dadi", Role.ELDER)
    with pytest.raises(ValueError):
        await Simulator(svc, build_server(svc)).turn(None, "hello")


def test_recipient_resolution_helpers(svc, family):
    amma, *_ = family
    person, start, end = resolve_recipient(svc, amma, "tell my beti I'm fine")
    assert person.name == "Priya"
    assert resolve_recipient(svc, amma, "tell nobody anything") is None
    assert extract_message("tell Rahul that I'm fine", 10) == "I'm fine"


# ---------------------------------------------------------------- LLM agent
class FakeLLM:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def chat(self, messages, *, tools=None, temperature=0.0):
        self.calls.append((messages, tools))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def with_llm(svc, llm):
    from dataclasses import replace

    return Simulator(replace(svc, llm=llm), build_server(svc))


async def test_llm_agent_uses_mcp_tools(svc, family):
    llm = FakeLLM([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "log_checkin", "arguments": '{"note": "hello"}'}}]},
        {"role": "assistant", "content": "Namaste Amma, all noted."},
    ])
    r = await with_llm(svc, llm).turn("Amma", "hello", "hi", use_llm=True)
    assert r.agent == "llm" and r.reply == "Namaste Amma, all noted." and names(r) == ["log_checkin"]
    assert any(t["function"]["name"] == "log_checkin" for t in llm.calls[0][1])
    assert "Hindi" in llm.calls[0][0][0]["content"]
    assert '"ok": true' in llm.calls[1][0][-1]["content"]  # tool result fed back to the model


async def test_llm_failure_falls_back_to_rules(svc, family):
    r = await with_llm(svc, FakeLLM([RuntimeError("quota")])).turn("Amma", "good morning", "en", use_llm=True)
    assert r.agent == "rules" and r.reply.startswith("Good morning")


async def test_llm_runaway_loop_falls_back(svc, family):
    loop = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "list_people", "arguments": "{}"}}]}
    r = await with_llm(svc, FakeLLM([loop] * 10)).turn("Amma", "hi", "en", use_llm=True)
    assert r.agent == "rules"


async def test_llm_ignored_unless_requested(svc, family):
    llm = FakeLLM([])
    r = await with_llm(svc, llm).turn("Amma", "hi", "en", use_llm=False)
    assert r.agent == "rules" and llm.calls == []
