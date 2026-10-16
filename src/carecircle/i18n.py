"""Spoken replies in English, Hindi and Marathi.

NOTE: Hindi and Marathi strings should be reviewed by a native speaker before production use.
"""

from __future__ import annotations

SPEECH_LANG = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
LANGUAGES = tuple(SPEECH_LANG)

_T: dict[str, dict[str, str]] = {
    "checkin_ok": {
        "en": "Good morning, {name}. I've noted your check-in.",
        "hi": "सुप्रभात {name}। मैंने आपका चेक-इन दर्ज कर लिया है।",
        "mr": "सुप्रभात {name}. मी तुमचा चेक-इन नोंदवला आहे.",
    },
    "concern_attention": {
        "en": "I'm sorry you're not feeling well. I've told {who}. Please rest, and speak to your doctor if it continues.",
        "hi": "मुझे दुख है कि आपकी तबीयत ठीक नहीं है। मैंने {who} को बता दिया है। आराम करें, और अगर यह जारी रहे तो डॉक्टर से बात करें।",
        "mr": "तुमची तब्येत बरी नसल्याचे ऐकून वाईट वाटले. मी {who} यांना कळवले आहे. विश्रांती घ्या, आणि त्रास चालू राहिला तर डॉक्टरांशी बोला.",
    },
    "concern_urgent": {
        "en": "Stay calm, {name}. I've alerted {who} right now. If you're in danger, please call your local emergency number.",
        "hi": "घबराइए मत, {name}। मैंने अभी {who} को सूचित कर दिया है। अगर आप खतरे में हैं तो कृपया अपने स्थानीय आपातकालीन नंबर पर कॉल करें।",
        "mr": "घाबरू नका, {name}. मी आत्ताच {who} यांना कळवले आहे. तुम्ही धोक्यात असाल तर कृपया तुमच्या स्थानिक आपत्कालीन क्रमांकावर कॉल करा.",
    },
    "reminders_due": {
        "en": "You have {n} reminder(s): {items}.",
        "hi": "आपके लिए {n} रिमाइंडर हैं: {items}।",
        "mr": "तुमच्यासाठी {n} स्मरणपत्रे आहेत: {items}.",
    },
    "messages_intro": {
        "en": "You have messages from your family.",
        "hi": "परिवार की तरफ़ से आपके लिए संदेश हैं।",
        "mr": "कुटुंबाकडून तुमच्यासाठी संदेश आहेत.",
    },
    "message_line": {
        "en": "{sender} says: {body}",
        "hi": "{sender} का संदेश: {body}",
        "mr": "{sender} यांचा संदेश: {body}",
    },
    "nothing_pending": {
        "en": "Nothing is waiting for you right now.",
        "hi": "अभी आपके लिए कुछ भी बाकी नहीं है।",
        "mr": "सध्या तुमच्यासाठी काहीही प्रलंबित नाही.",
    },
    "confirmed_taken": {
        "en": "Great, I've marked {item} as taken.",
        "hi": "बहुत अच्छा, मैंने {item} लेना दर्ज कर दिया है।",
        "mr": "छान, मी {item} घेतल्याची नोंद केली आहे.",
    },
    "confirmed_skipped": {
        "en": "Okay, I've noted that you skipped {item}.",
        "hi": "ठीक है, मैंने दर्ज किया कि आपने {item} छोड़ा।",
        "mr": "ठीक आहे, तुम्ही {item} वगळल्याची नोंद केली आहे.",
    },
    "which_reminder": {
        "en": "Which one did you mean: {options}?",
        "hi": "आपका मतलब कौन सा था: {options}?",
        "mr": "तुम्हाला कोणते म्हणायचे आहे: {options}?",
    },
    "nothing_to_confirm": {
        "en": "I don't see anything waiting to be confirmed.",
        "hi": "मुझे पुष्टि के लिए कुछ भी बाकी नहीं दिख रहा।",
        "mr": "पुष्टीसाठी काहीही प्रलंबित दिसत नाही.",
    },
    "message_sent": {
        "en": "Done. I'll pass your message to {to}.",
        "hi": "ठीक है, मैं आपका संदेश {to} तक पहुँचा दूँगा।",
        "mr": "ठीक आहे, मी तुमचा संदेश {to} यांना पोहोचवतो.",
    },
    "who_message": {
        "en": "Who should I send it to?",
        "hi": "किसको भेजना है?",
        "mr": "कोणाला पाठवू?",
    },
    "generic_error": {
        "en": "Sorry, something went wrong. Please try again.",
        "hi": "क्षमा करें, कुछ गड़बड़ हो गई। कृपया फिर कोशिश करें।",
        "mr": "क्षमस्व, काहीतरी चुकले. कृपया पुन्हा प्रयत्न करा.",
    },
    "nudge": {
        "en": "Good morning {name}! Just say hello when you're ready, so your family knows you're okay.",
        "hi": "सुप्रभात {name}! जब आप तैयार हों तो नमस्ते कह दीजिए, ताकि परिवार को पता रहे कि आप ठीक हैं।",
        "mr": "सुप्रभात {name}! तुम्ही तयार झाल्यावर नमस्कार म्हणा, म्हणजे कुटुंबाला कळेल की तुम्ही ठीक आहात.",
    },
    "and": {"en": " and ", "hi": " और ", "mr": " आणि "},
    "family": {"en": "your family", "hi": "आपके परिवार", "mr": "तुमच्या कुटुंबाला"},
}


def normalize_language(code: str | None) -> str:
    base = (code or "en").strip().lower().split("-")[0]
    return base if base in SPEECH_LANG else "en"


def t(lang: str | None, key: str, **values: object) -> str:
    entry = _T[key]
    return entry.get(normalize_language(lang), entry["en"]).format(**values)


def join_names(lang: str | None, names: list[str]) -> str:
    if not names:
        return t(lang, "family")
    return t(lang, "and").join(names) if len(names) <= 2 else ", ".join(names[:-1]) + t(lang, "and") + names[-1]


def keys() -> list[str]:
    return list(_T)


def missing_translations() -> dict[str, list[str]]:
    return {
        key: [lang for lang in LANGUAGES if lang not in entry]
        for key, entry in _T.items()
        if any(lang not in entry for lang in LANGUAGES)
    }
