"""Rule-based concern detection for free-text check-ins.

Design goals
  * Fast, offline and deterministic: the first line of defence never needs a network call.
  * Multilingual: English plus Hindi/Marathi (Devanagari and common romanisations).
  * Conservative about negation ("no chest pain") but never negates phrases that carry
    their own negation ("can't breathe").
  * Pluggable: a second-opinion classifier (e.g. an LLM) can only *raise* severity.

This is a family-notification aid, NOT a medical or emergency service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from .models import Severity


@dataclass(frozen=True)
class Rule:
    category: str
    severity: Severity
    pattern: re.Pattern[str]
    negatable: bool = True


def _rule(category: str, severity: Severity, pattern: str, negatable: bool = True) -> Rule:
    return Rule(category, severity, re.compile(pattern, re.IGNORECASE | re.UNICODE), negatable)


U, A = Severity.URGENT, Severity.ATTENTION

RULES: tuple[Rule, ...] = (
    # ---- urgent ---------------------------------------------------------
    _rule("fall", U, r"\b(fell|fallen|had a fall|slipped and fell|fell down)\b"),
    _rule("fall", U, r"\bgir\s+(gaya|gayi|gai|padi|pada)\b|गिर\s*(गया|गई|गयी|पड़ी|पड़ा)|पडलो|पडले|पडली"),
    _rule("chest", U, r"\bchest\s+(pain|pains|tight|tightness|pressure|hurts?)\b|\bheart\s+(attack|pain)\b"),
    _rule("chest", U, r"\bseene\s+(me|mein)\s+dard\b|सीने\s+में\s+दर्द|छातीत\s+(दुखत|दुखतंय|दुखतय)"),
    _rule("breathing", U, r"\b(can'?t|cannot|unable to)\s+breathe\b|\btrouble\s+breathing\b|\bshort\s+of\s+breath\b|\bbreathless(ness)?\b", False),
    _rule("breathing", U, r"\bsaans\s+(nahi|nahin|lene\s+mein)\b|सांस\s+(नहीं|लेने)|साँस\s+(नहीं|लेने)|श्वास\s+घेता\s+येत\s+नाही", False),
    _rule("collapse", U, r"\b(faint(ed|ing)?|passed\s+out|blacked\s+out|unconscious|collapsed)\b|बेहोश|बेशुद्ध"),
    _rule("stroke", U, r"\bstroke\b|\bslurred\s+speech\b|\bface\s+(is\s+)?drooping\b|\bcan'?t\s+(move|feel)\s+(my\s+)?(arm|leg|face)\b", False),
    _rule("bleeding", U, r"\bbleeding\s+(a\s+lot|heavily|badly)\b|\bwon'?t\s+stop\s+bleeding\b", False),
    _rule("help", U, r"\b(emergency|call\s+(an\s+)?ambulance|help\s+me|need\s+help|bachao)\b|\bmadad\b|मदद|बचाओ|वाचवा", False),
    _rule("distress", U, r"\b(want\s+to\s+die|don'?t\s+want\s+to\s+live|end\s+my\s+life)\b", False),
    # ---- attention ------------------------------------------------------
    _rule("dizzy", A, r"\b(dizz(y|iness)|light-?headed|vertigo)\b|\bchakkar\b|चक्कर"),
    _rule("pain", A, r"\b(pain|painful|ache|aching|hurts?|sore)\b|\bdard\b|दर्द|दुखत"),
    _rule("fever", A, r"\b(fever|temperature|chills)\b|बुखार|\bbukhar\b|ताप\b"),
    _rule("nausea", A, r"\b(vomit(ing)?|nausea|nauseous|threw\s+up)\b|\bulti\b|उल्टी"),
    _rule("weakness", A, r"\b(weak|weakness|exhausted)\b|\bkamzori\b|कमजोरी|कमज़ोरी|अशक्त"),
    _rule("confusion", A, r"\b(confused|disoriented|lost\s+my\s+way|forgot\s+where)\b|\bdon'?t\s+remember\b", False),
    _rule("not_eating", A, r"\b(didn'?t|haven'?t|did\s+not|have\s+not)\s+(eat|eaten|had\s+(any\s+)?food)\b|\bskipped\s+(breakfast|lunch|dinner|meals?)\b", False),
    _rule("sleep", A, r"\b(couldn'?t|could\s+not|can'?t)\s+sleep\b|\bno\s+sleep\b|\binsomnia\b", False),
    _rule("loneliness", A, r"\b(lonely|alone\s+all\s+day|feeling\s+low|so\s+sad|depressed)\b|अकेला|अकेली|एकटा|एकटी"),
)

_NEGATORS = frozenset(
    {"no", "not", "never", "without", "nahi", "nahin", "na", "नहीं", "नही", "ना", "नको", "नाही"}
)
# Hindi/Marathi are verb-final: the negator follows the symptom ("चक्कर नहीं आ रहे").
_TRAILING_NEGATORS = frozenset({"nahi", "nahin", "नहीं", "नही", "नाही", "नको"})
_CLAUSE_BREAK = re.compile(r"[.,;:!?\n]|\bbut\b|\bhowever\b|\blekin\b|\bpar\b|लेकिन|पर\b", re.IGNORECASE)
# Whitespace tokenisation: \w would split Devanagari words at vowel signs (matras).
_WORD = re.compile(r"[^\s.,;:!?()\"\u201c\u201d]+")


def _negated(text: str, start: int, window: int = 3) -> bool:
    """True if a negator appears within `window` words before `start` in the same clause."""
    head = text[:start]
    breaks = list(_CLAUSE_BREAK.finditer(head))
    clause = head[breaks[-1].end():] if breaks else head
    words = [w.lower() for w in _WORD.findall(clause)][-window:]
    return any(w in _NEGATORS or w.endswith("n't") for w in words)


def _negated_after(text: str, end: int, window: int = 2) -> bool:
    """True if a verb-final negator follows `end` within `window` words in the same clause."""
    tail = text[end:]
    brk = _CLAUSE_BREAK.search(tail)
    clause = tail[: brk.start()] if brk else tail
    words = [w.lower() for w in _WORD.findall(clause)][:window]
    return any(w in _TRAILING_NEGATORS for w in words)


@dataclass(frozen=True)
class Match:
    category: str
    severity: Severity
    text: str


@dataclass(frozen=True)
class Assessment:
    severity: Severity = Severity.INFO
    matches: tuple[Match, ...] = field(default_factory=tuple)

    @property
    def categories(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for m in self.matches:
            seen.setdefault(m.category, None)
        return tuple(seen)

    @property
    def concerning(self) -> bool:
        return self.severity >= Severity.ATTENTION

    def describe(self) -> str:
        if not self.matches:
            return "no concerns detected"
        return ", ".join(self.categories)

    def raised_to(self, severity: Severity, category: str, text: str = "") -> "Assessment":
        if severity <= self.severity:
            return self
        return Assessment(severity, self.matches + (Match(category, severity, text),))


class SecondOpinion(Protocol):
    """Optional extra classifier. Its verdict can only raise severity, never lower it."""

    def assess(self, text: str) -> "Assessment": ...


class SafetyClassifier:
    def __init__(
        self,
        rules: Iterable[Rule] = RULES,
        second_opinion: SecondOpinion | None = None,
    ) -> None:
        self._rules = tuple(rules)
        self._second = second_opinion

    def assess(self, text: str) -> Assessment:
        text = (text or "").strip()
        if not text:
            return Assessment()
        matches: list[Match] = []
        for rule in self._rules:
            for found in rule.pattern.finditer(text):
                if rule.negatable and (
                    _negated(text, found.start()) or _negated_after(text, found.end())
                ):
                    continue
                matches.append(Match(rule.category, rule.severity, found.group(0)))
        severity = max((m.severity for m in matches), default=Severity.INFO)
        result = Assessment(severity, tuple(matches))
        if self._second is not None:
            try:
                extra = self._second.assess(text)
            except Exception:  # a failing second opinion must never hide a rule hit
                return result
            if extra.severity > result.severity:
                result = Assessment(extra.severity, result.matches + extra.matches)
        return result
