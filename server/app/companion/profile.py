"""The person's profile, filled in once on the setup page (by family/caregiver with the person),
editable any time. It turns the generic assistant into *their* companion: who they are, the
people in their life, their routine, what they enjoy, what cheers them up, what to handle gently.

Stored as one JSON document (storage/db.py `profile` table). Missing fields fall back to
DEFAULT, and the names fall back to ELDER_NAME / COMPANION_NAME from config.
"""

import copy
import re
from datetime import datetime

from app import config
from app.storage import db

STYLES = {
    "warm": "warm, gentle and patient",
    "cheerful": "cheerful, chatty and lightly humorous",
    "calm": "calm, respectful and unhurried",
}

# Curated edge-tts voices offered on the setup page (any edge-tts voice id also works).
VOICES = [
    {"id": "en-IN-NeerjaNeural", "label": "Neerja · Indian English · female"},
    {"id": "en-IN-NeerjaExpressiveNeural", "label": "Neerja (expressive) · Indian English · female"},
    {"id": "en-IN-PrabhatNeural", "label": "Prabhat · Indian English · male"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia · British English · female"},
    {"id": "en-US-AvaMultilingualNeural", "label": "Ava · American English · female"},
    {"id": "en-US-AndrewMultilingualNeural", "label": "Andrew · American English · male"},
]

PRONOUNS = {  # subject, object, possessive, "is"-contraction
    "she": ("she", "her", "her", "she's"),
    "he": ("he", "him", "his", "he's"),
    "they": ("they", "them", "their", "they're"),
}

DEFAULT = {
    "elder": {"full_name": "", "preferred_name": "", "pronouns": "they", "age": "", "city": "",
              "languages": "", "background": "", "living": ""},
    "people": [],  # [{name, relation, notes, birthday ("DD-MM" or "")}]
    "routine": {"wake_time": "", "sleep_time": "", "daily": ""},
    "interests": "",
    "cheer_up": "",
    "activities": "",
    "health_notes": "",
    "sensitive_topics": "",
    "companion": {"name": "", "voice": config.TTS_EDGE_VOICE, "style": "warm", "address_as": ""},
    "family_contact": {"name": "", "relation": ""},
    "reminders": [],  # setup-page reminders: [{title, kind, time, days, notes}] (synced to the table)
}

MAX_TEXT = 600
MAX_PEOPLE = 30


def _merge(base: dict, data: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (data or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        elif k in out:
            out[k] = v
    return out


def _clean(value, limit=MAX_TEXT):
    return value.strip()[:limit] if isinstance(value, str) else value


def normalize(data: dict) -> dict:
    """Validate/trim a profile coming from the setup page."""
    p = _merge(DEFAULT, data)
    for section in ("elder", "routine", "companion", "family_contact"):
        p[section] = {k: _clean(v) for k, v in p[section].items()}
    for key in ("interests", "cheer_up", "activities", "health_notes", "sensitive_topics"):
        p[key] = _clean(p[key])
    if p["elder"]["pronouns"] not in PRONOUNS:
        p["elder"]["pronouns"] = "they"
    if p["companion"]["style"] not in STYLES:
        p["companion"]["style"] = "warm"
    p["people"] = [
        {k: _clean(person.get(k, ""), 200) for k in ("name", "relation", "notes", "birthday")}
        for person in (p["people"] or [])[:MAX_PEOPLE] if _clean(person.get("name", ""))
    ]
    reminders = []
    for r in p["reminders"] or []:
        title = _clean(r.get("title", ""), 120)
        if not title:
            continue
        time = _clean(r.get("time") or "", 5) or None
        reminders.append({"title": title, "kind": r.get("kind") or "task", "time": time,
                          "days": _clean(r.get("days") or "daily", 40), "notes": _clean(r.get("notes", ""), 200)})
    p["reminders"] = reminders
    return p


def load() -> dict:
    """The current profile merged with defaults; `configured` is False until setup is saved."""
    stored = db.get_profile()
    p = _merge(DEFAULT, stored or {})
    p["configured"] = stored is not None
    return p


def save(data: dict) -> dict:
    p = normalize(data)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    db.save_profile(p, now)
    db.replace_reminders("setup", p["reminders"], now)
    return load()


# ---------------------------------------------------------------- convenience accessors
def elder_name(p: dict) -> str:
    return p["elder"]["preferred_name"] or p["elder"]["full_name"] or config.ELDER_NAME


def address_as(p: dict) -> str:
    return p["companion"]["address_as"] or elder_name(p)


def companion_name(p: dict) -> str:
    return p["companion"]["name"] or config.COMPANION_NAME


def pronouns(p: dict) -> tuple:
    return PRONOUNS.get(p["elder"]["pronouns"], PRONOUNS["they"])


def voice(p: dict) -> str:
    return p["companion"]["voice"] or config.TTS_EDGE_VOICE


# --- Sensitive topics (enforced in code, not only by the prompt) -------------------------------
# In testing the LLM brought up the late husband by name unprompted (docs/EVALUATION.md §6). So until
# the person mentions a sensitive topic in this conversation, its names are left out of everything
# the LLM sees (profile, memories, greeting hook) and only a generic "don't raise it" rule remains.
_NOT_NAMES = {"Her", "His", "Their", "The", "She", "He", "They", "Let", "Don't", "Never", "Only", "When",
              "If", "And", "But", "Please", "Avoid", "Do", "Not", "Late", "My", "Our", "Talk", "Him", "Them"}
_RELATIONS = ("husband", "wife", "son", "daughter", "mother", "father", "brother", "sister", "partner",
              "grandson", "granddaughter", "friend", "dog", "cat", "pet")


def sensitive_names(p: dict) -> set:
    """Capitalised names in the sensitive-topics field, e.g. {"Raman"}."""
    words = re.findall(r"\b[A-Z][a-z]{2,}\b", p.get("sensitive_topics", ""))
    return {w for w in words if w not in _NOT_NAMES}


def sensitive_terms(p: dict) -> set:
    """Names plus relation words used in the sensitive topics ("husband"), lowercase."""
    text = p.get("sensitive_topics", "").lower()
    return {n.lower() for n in sensitive_names(p)} | {r for r in _RELATIONS if re.search(rf"\b{r}\b", text)}


def sensitive_opened(p: dict, user_texts: list) -> bool:
    """True if the person themself brought up a sensitive topic in these messages."""
    terms = sensitive_terms(p)
    joined = " ".join(user_texts).lower()
    return any(re.search(rf"\b{re.escape(t)}\b", joined) for t in terms)


def mentions_sensitive(p: dict, text: str) -> bool:
    return any(re.search(rf"\b{re.escape(n)}\b", text or "") for n in sensitive_names(p))


def _scrub(text: str, names: set) -> str:
    """Drops the sentences that name a sensitive person."""
    if not names or not text:
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(x for x in parts if not any(re.search(rf"\b{re.escape(n)}\b", x) for n in names))


def describe(p: dict, sensitive_open: bool = True) -> str:
    """The profile as plain text for the LLM's system prompt (empty fields are skipped).
    sensitive_open=False: the sensitive topic hasn't come up in this conversation, so its names
    are removed everywhere and only a generic "don't raise it" rule is given."""
    hide = set() if sensitive_open else sensitive_names(p)
    e, name = p["elder"], elder_name(p)
    lines = [f"About {name}:"]
    facts = [
        f"full name {e['full_name']}" if e["full_name"] and e["full_name"] != name else "",
        f"age {e['age']}" if e["age"] else "",
        f"lives in {e['city']}" if e["city"] else "",
        f"speaks {e['languages']}" if e["languages"] else "",
    ]
    if any(facts):
        lines.append("- " + ", ".join(f for f in facts if f))
    for label, value in (("Background", e["background"]), ("Living situation", e["living"])):
        value = _scrub(value, hide)
        if value:
            lines.append(f"- {label}: {value}")
    people = [x for x in p["people"] if x["name"] not in hide]
    if people:
        lines.append(f"People in {name}'s life:")
        for person in people:
            notes = _scrub(person["notes"], hide)
            extra = f": {notes}" if notes else ""
            bday = f" (birthday {person['birthday']})" if person["birthday"] else ""
            lines.append(f"- {person['name']} ({person['relation'] or 'relation unknown'}){bday}{extra}")
    r = p["routine"]
    routine = ", ".join(x for x in (f"wakes around {r['wake_time']}" if r["wake_time"] else "",
                                    f"sleeps around {r['sleep_time']}" if r["sleep_time"] else "") if x)
    daily = _scrub(r["daily"], hide)
    if routine or daily:
        lines.append(f"Daily life: {'; '.join(x for x in (routine, daily) if x)}")
    for label, key in (("Enjoys", "interests"), ("Things that cheer them up", "cheer_up"),
                       ("Activities to suggest", "activities")):
        value = _scrub(p[key], hide)
        if value:
            lines.append(f"{label}: {value}")
    if p["health_notes"]:
        lines.append(f"Health notes (be gentle, never give medical advice): {p['health_notes']}")
    if p["sensitive_topics"]:
        if sensitive_open:
            lines.append("Sensitive topics (they brought this up: listen kindly, follow their lead, don't push): "
                         f"{p['sensitive_topics']}")
        else:
            lines.append("Sensitive topics: there is something painful in their life (such as a loss). Never "
                         "bring up death, loss, grief or late family members yourself. If they bring it up, "
                         "listen kindly.")
    return "\n".join(lines)


def safety_background(p: dict) -> str:
    """Context for the self-harm screen (names included, never shown to the companion LLM)."""
    return " ".join(x for x in (p["elder"]["living"], p["sensitive_topics"]) if x)
