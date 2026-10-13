import pytest

from carecircle.models import Severity
from carecircle.safety import Assessment, SafetyClassifier

clf = SafetyClassifier()


@pytest.mark.parametrize(
    "text, severity",
    [
        ("Good morning, slept well and had my tea", Severity.INFO),
        ("", Severity.INFO),
        ("I feel dizzy", Severity.ATTENTION),
        ("my knee hurts a little", Severity.ATTENTION),
        ("I have not eaten since yesterday", Severity.ATTENTION),
        ("I haven't eaten anything", Severity.ATTENTION),
        ("I fell in the bathroom", Severity.URGENT),
        ("I have chest pain", Severity.URGENT),
        ("I can't breathe properly", Severity.URGENT),
        ("I think I'm going to faint", Severity.URGENT),
        ("please help me", Severity.URGENT),
        ("mujhe chakkar aa raha hai", Severity.ATTENTION),
        ("seene mein dard ho raha hai", Severity.URGENT),
        ("मुझे चक्कर आ रहे हैं", Severity.ATTENTION),
        ("मैं गिर गई", Severity.URGENT),
        ("मला छातीत दुखतंय", Severity.URGENT),
        ("I don't want to live like this", Severity.URGENT),
    ],
)
def test_severity(text, severity):
    assert clf.assess(text).severity == severity, clf.assess(text)


@pytest.mark.parametrize(
    "text",
    [
        "no chest pain today",
        "I am not dizzy anymore",
        "I didn't fall, don't worry",
        "no fever, no pain",
        "मुझे चक्कर नहीं आ रहे",
        "mujhe chakkar nahi aa raha",
    ],
)
def test_negation_suppresses(text):
    assert clf.assess(text).severity == Severity.INFO


def test_clause_break_prevents_negation_leak():
    assert clf.assess("No tablets missed, but I feel dizzy").severity == Severity.ATTENTION


def test_builtin_negation_is_not_negated():
    assert clf.assess("no, I really can't breathe").severity == Severity.URGENT


def test_categories_and_description():
    result = clf.assess("I feel dizzy and my head hurts")
    assert set(result.categories) == {"dizzy", "pain"}
    assert result.concerning
    assert clf.assess("all good").describe() == "no concerns detected"


class _Raises:
    def assess(self, text):  # noqa: D401
        raise RuntimeError("boom")


class _Escalates:
    def assess(self, text):
        return Assessment().raised_to(Severity.URGENT, "llm", "x")


class _Downgrades:
    def assess(self, text):
        return Assessment()


def test_second_opinion_can_only_raise():
    assert SafetyClassifier(second_opinion=_Escalates()).assess("hello").severity == Severity.URGENT
    assert SafetyClassifier(second_opinion=_Downgrades()).assess("I fell").severity == Severity.URGENT


def test_failing_second_opinion_is_ignored():
    assert SafetyClassifier(second_opinion=_Raises()).assess("I fell").severity == Severity.URGENT


def test_hindi_trailing_negation_does_not_leak_across_clauses():
    assert clf.assess("चक्कर नहीं, लेकिन घुटने में दर्द है").severity == Severity.ATTENTION
