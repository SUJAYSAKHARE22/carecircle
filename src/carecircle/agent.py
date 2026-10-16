"""The 'Alexa+' stand-in used by the simulator.

Both agents talk to CareCircle exclusively through the MCP protocol (a real MCP client session
against the real server), so the tool-call log in the UI is genuine MCP traffic.

* RuleBasedAgent - offline, deterministic, multilingual. Guarantees a reliable demo.
* LLMAgent       - optional function-calling loop over the MCP tool catalogue.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from mcp import Client

from .i18n import SPEECH_LANG, join_names, normalize_language, t
from .llm import LLMClient
from .models import Person
from .server import INSTRUCTIONS
from .services import Services

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    ms: float


@dataclass
class TurnResult:
    reply: str
    language: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    agent: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "language": self.language,
            "speech_lang": SPEECH_LANG[self.language],
            "agent": self.agent,
            "tool_calls": [
                {"name": c.name, "arguments": c.arguments, "result": c.result, "ms": round(c.ms, 1)}
                for c in self.tool_calls
            ],
        }


# ---------------------------------------------------------------------------- vocabulary
_RELATIONS = {
    "son": ("son", "beta", "bete", "बेटा", "बेटे", "मुलगा", "मुलाला"),
    "daughter": ("daughter", "beti", "बेटी", "मुलगी", "मुलीला"),
    "grandson": ("grandson", "pota", "पोता", "नातू"),
    "granddaughter": ("granddaughter", "poti", "पोती", "नात"),
}
_MESSAGE_VERBS = re.compile(
    r"\b(tell|message|inform|let\s+\w+\s+know|bol\s*do|bolo|kaho|keh\s*do|bata\s*do|sang|sanga)\b"
    r"|बोल\s*दो|बोलो|कहो|कह\s*दो|बता\s*दो|सांगा|सांग|कळवा",
    re.IGNORECASE,
)
_TAKEN = re.compile(
    r"\b(took|taken|had|swallowed|finished|le\s+li|li|khali|khayi|khai|liya|ghetli)\b"
    r"|ले\s*ली|ली\s*है|खा\s*ली|खा\s*लिया|लिया|घेतली|घेतले",
    re.IGNORECASE,
)
_SKIPPED = re.compile(
    r"\b(skip(ped)?|didn'?t\s+take|did\s+not\s+take|not\s+taking|forgot|nahi\s+li|nahin\s+li)\b"
    r"|नहीं\s*ली|नही\s*ली|छोड़|नाही\s*घेतली|विसरलो|विसरले",
    re.IGNORECASE,
)
_MEDICINE = re.compile(
    r"\b(tablets?|pills?|medicines?|meds?|capsules?|dawai|dawa|goli|vitamin)\b|दवा|दवाई|गोली|गोळी|औषध",
    re.IGNORECASE,
)
_PENDING = re.compile(
    r"\b(any\s+(messages?|reminders?)|what\s+(do\s+i\s+have|is\s+pending)|anything\s+for\s+me|"
    r"my\s+(messages?|reminders?)|read\s+(my\s+)?messages?)\b"
    r"|कोई\s+संदेश|मेरे\s+(संदेश|रिमाइंडर)|क्या\s+बाकी|काही\s+संदेश|माझे\s+संदेश",
    re.IGNORECASE,
)
_STOPWORDS = {
    "i", "my", "the", "a", "an", "took", "taken", "have", "had", "already", "just", "swallowed",
    "finished", "please", "now", "today", "this", "morning", "li", "maine", "main", "meri", "mera",
    "apni", "did", "not", "take", "taking", "didn't", "skip", "skipped", "forgot", "nahi", "nahin",
    "मैंने", "मैं", "मी", "मेरी", "मेरा", "मेरे", "माझी", "माझे", "माझा", "अपनी", "अपना", "ले", "है",
    "हूँ", "तो", "भी", "ने", "ही", "आज", "अभी",
}
_GENERIC_MED = {
    "tablet", "tablets", "pill", "pills", "medicine", "medicines", "med", "meds", "capsule",
    "capsules", "dawai", "dawa", "goli", "दवा", "दवाई", "गोली", "गोळी", "औषध",
}
_MOOD_WORDS = {
    5: re.compile(r"\b(great|wonderful|excellent|fantastic)\b|बहुत\s+अच्छ", re.IGNORECASE),
    4: re.compile(r"\b(good|fine|well|happy|better)\b|अच्छ[ाीे]|ठीक\s+हूँ|ठीक\s+हूं|बरा|बरी", re.IGNORECASE),
    2: re.compile(r"\b(bad|tired|low|sad|unwell|weak)\b|थक", re.IGNORECASE),
}
_TOKEN = re.compile(r"[^\s.,;:!?()\"'\u201c\u201d]+")


def _mood(text: str) -> int | None:
    for score in (5, 4, 2):
        if _MOOD_WORDS[score].search(text):
            return score
    return None


def _hint(text: str) -> str | None:
    """Content words that name a specific reminder ('blood pressure'), minus generic filler."""
    cleaned = _TAKEN.sub(" ", _SKIPPED.sub(" ", text.lower()))
    words = [w for w in _TOKEN.findall(cleaned) if w not in _STOPWORDS and w not in _GENERIC_MED]
    return " ".join(words) or None


def _members(services: Services, elder: Person) -> list[tuple[Person, str | None]]:
    return [(m, services.people.relation(elder.id, m.id)) for m in services.people.members_of(elder.id)]


def resolve_recipient(services: Services, elder: Person, text: str) -> tuple[Person, int, int] | None:
    """Find a circle member mentioned by name or relation; return (person, start, end)."""
    lowered = text.lower()
    best: tuple[Person, int, int] | None = None
    for member, relation in _members(services, elder):
        candidates = [member.name.lower()]
        if relation:
            key = relation.strip().lower()
            candidates += [w.lower() for w in _RELATIONS.get(key, ())] + [key]
        for cand in candidates:
            idx = lowered.find(cand)
            if idx != -1 and (best is None or idx < best[1]):
                best = (member, idx, idx + len(cand))
    return best


_LEAD = re.compile(r"^[\s,:\-]*(that|ki|की|कि|to|se|से|ko|को|ला|ना)?[\s,:\-]*", re.IGNORECASE)


def extract_message(text: str, end: int) -> str:
    body = _LEAD.sub("", text[end:], count=1).strip()
    body = _MESSAGE_VERBS.sub("", body).strip(" ,.")
    body = _LEAD.sub("", body, count=1).strip(" ,.")
    return body or text.strip()


# ---------------------------------------------------------------------------- rule-based
class RuleBasedAgent:
    name = "rules"

    def __init__(self, services: Services) -> None:
        self._s = services

    async def respond(self, elder: Person, text: str, call: ToolCaller, lang: str) -> str:
        text = text.strip()
        name = elder.name
        member = resolve_recipient(self._s, elder, text)

        if member and _MESSAGE_VERBS.search(text):
            person, _, end = member
            body = extract_message(text, end)
            res = await call("leave_message", {"sender": name, "recipient": person.name, "message": body})
            return t(lang, "message_sent", to=res.get("to", person.name)) if res.get("ok") else t(lang, "generic_error")

        if _MESSAGE_VERBS.search(text) and not member and not _TAKEN.search(text):
            return t(lang, "who_message")

        wants_skip = bool(_SKIPPED.search(text)) and bool(_MEDICINE.search(text) or _hint(text))
        wants_take = bool(_TAKEN.search(text)) and bool(_MEDICINE.search(text))
        if wants_skip or wants_take:
            args: dict[str, Any] = {"person": name, "status": "skipped" if wants_skip else "taken"}
            hint = _hint(text)
            if hint:
                args["reminder"] = hint
            res = await call("confirm_reminder", args)
            if res.get("ok"):
                key = "confirmed_skipped" if wants_skip else "confirmed_taken"
                return t(lang, key, item=res["reminder"])
            if res.get("needs_clarification"):
                return t(lang, "which_reminder", options=", ".join(res["options"]))
            return t(lang, "nothing_to_confirm")

        if _PENDING.search(text):
            return await self._pending(elder, call, lang, lead=None)

        # Default: treat the utterance as a check-in.
        args = {"person": name, "note": text}
        mood = _mood(text)
        if mood:
            args["mood"] = mood
        res = await call("log_checkin", args)
        if not res.get("ok"):
            return t(lang, "generic_error")
        level = res["concern_level"]
        who = join_names(lang, res.get("will_notify", []))
        if level == "urgent":
            lead = t(lang, "concern_urgent", name=name, who=who)
        elif level == "attention":
            lead = t(lang, "concern_attention", who=who)
        else:
            lead = t(lang, "checkin_ok", name=name)
        if res["pending_reminders"] or res["unread_messages"]:
            return await self._pending(elder, call, lang, lead=lead)
        return lead

    async def _pending(self, elder: Person, call: ToolCaller, lang: str, lead: str | None) -> str:
        res = await call("get_pending_items", {"person": elder.name})
        parts = [lead] if lead else []
        if not res.get("ok"):
            return " ".join(parts + [t(lang, "generic_error")])
        reminders, messages = res["reminders_due"], res["messages"]
        if reminders:
            parts.append(t(lang, "reminders_due", n=len(reminders), items=", ".join(r["reminder"] for r in reminders)))
        if messages:
            parts.append(t(lang, "messages_intro"))
            parts += [t(lang, "message_line", sender=m["from"], body=m["message"]) for m in messages]
        if not reminders and not messages:
            parts.append(t(lang, "nothing_pending"))
        return " ".join(parts)


# ---------------------------------------------------------------------------- LLM agent
class LLMAgent:
    name = "llm"
    MAX_STEPS = 5

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    @staticmethod
    def _tool_specs(tools: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (tool.description or "")[:1000],
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    async def respond(self, elder: Person, text: str, call: ToolCaller, lang: str, tools: list[Any]) -> str:
        language = {"hi": "Hindi", "mr": "Marathi"}.get(lang, "English")
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": f"{INSTRUCTIONS}\nYou are speaking with {elder.name}. Reply ONLY in {language}, "
                "in one to three short spoken sentences, no markdown or emoji.",
            },
            {"role": "user", "content": text},
        ]
        specs = self._tool_specs(tools)
        for _ in range(self.MAX_STEPS):
            message = self._client.chat(messages, tools=specs)
            calls = message.get("tool_calls") or []
            if not calls:
                content = (message.get("content") or "").strip()
                if not content:
                    raise RuntimeError("LLM returned an empty reply")
                return content
            messages.append(message)
            for tc in calls:
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await call(tc["function"]["name"], args)
                messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, ensure_ascii=False)}
                )
        raise RuntimeError("LLM did not finish within the step limit")


# ---------------------------------------------------------------------------- simulator
class Simulator:
    """Runs one spoken turn end to end through a real MCP client session."""

    def __init__(self, services: Services, server: Any) -> None:
        self._s = services
        self._server = server
        self._rules = RuleBasedAgent(services)
        self._llm = LLMAgent(services.llm) if services.llm else None

    @property
    def llm_enabled(self) -> bool:
        return self._llm is not None

    async def turn(self, person: str | None, text: str, lang: str | None = None, use_llm: bool = False) -> TurnResult:
        text = (text or "").strip()
        if not text:
            raise ValueError("Say something first")
        if len(text) > 600:
            raise ValueError("That was a bit long; please keep it under 600 characters")
        elder = self._s.people.find(person) if person else self._only_elder()
        language = normalize_language(lang or elder.language)
        calls: list[ToolCall] = []

        async with Client(self._server) as client:

            async def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
                started = time.perf_counter()
                result = await client.call_tool(name, args)
                payload = result.structured_content or {"ok": False, "error": "no structured result"}
                calls.append(ToolCall(name, args, payload, (time.perf_counter() - started) * 1000))
                return payload

            if use_llm and self._llm:
                try:
                    tools = (await client.list_tools()).tools
                    reply = await self._llm.respond(elder, text, call, language, tools)
                    return TurnResult(reply, language, calls, "llm")
                except Exception:
                    calls.clear()  # fall back to the deterministic path
            reply = await self._rules.respond(elder, text, call, language)
            return TurnResult(reply, language, calls, "rules")

    def _only_elder(self) -> Person:
        from .models import Role

        elders = self._s.people.list(Role.ELDER)
        if len(elders) != 1:
            raise ValueError("Choose which elder is speaking")
        return elders[0]
