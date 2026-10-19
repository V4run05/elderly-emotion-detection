""""Get to know you": a spoken first conversation that fills in the profile.

Instead of (or as well as) the setup form, the companion asks a short series of questions and
turns each answer into profile fields. Topics already filled in the profile are skipped, the
person can say "skip", and the profile is saved after every answer, so stopping early keeps
what was learned. These conversations are NOT check-ins: they don't count towards the mood
trend, the alerts or the personal baseline.

Per answer:  audio -> Whisper -> transcript
             transcript --(gpt-oss-120b, strict JSON)--> profile patch --merge--> saved profile
             transcript + next question --(gpt-oss-20b)--> short acknowledgement + next question
"""

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app import config
from app.analysis import audio
from app.companion import profile as profile_mod
from app.dialogue import llm, stt, tts
from app.storage import db

logger = logging.getLogger("uvicorn.error")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="onboarding")


class OnboardingError(Exception):
    """A problem the client should show to the user."""


# (key, question, already-filled check)
TOPICS = [
    ("name", "What would you like me to call you?",
     lambda p: bool(p["elder"]["preferred_name"])),
    ("companion", "By the way, my name is {companion}. Would you like to call me something else, or is {companion} fine?",
     lambda p: bool(p["companion"]["name"])),
    ("about", "Tell me a little about yourself. Where did you grow up, and what work did you do?",
     lambda p: bool(p["elder"]["background"])),
    ("living", "Who do you live with at home, and is any of your family nearby?",
     lambda p: bool(p["elder"]["living"])),
    ("people", "Who are the people who matter most to you? Tell me their names and how you know them.",
     lambda p: len(p["people"]) >= 2),
    ("routine", "What does a usual day look like for you, from morning to night?",
     lambda p: bool(p["routine"]["daily"])),
    ("interests", "What do you enjoy doing? Any hobbies, music or shows you love?",
     lambda p: bool(p["interests"])),
    ("cheer_up", "When you're feeling a bit low, what usually cheers you up?",
     lambda p: bool(p["cheer_up"])),
    ("reminders", "Are there any medicines or daily tasks you'd like me to remind you about? Tell me the times too.",
     lambda p: bool(p["reminders"])),
    ("avoid", "Last one. Is there anything you'd rather I didn't bring up?",
     lambda p: bool(p["sensitive_topics"])),
]
QUESTIONS = {k: q for k, q, _ in TOPICS}


def question(key: str, p: dict) -> str:
    """The question text with the companion's current name filled in."""
    return QUESTIONS[key].format(companion=profile_mod.companion_name(p))

_str = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "preferred_name": _str, "full_name": _str, "pronouns": {"type": "string", "enum": ["she", "he", "they", "unknown"]},
        "age": _str, "city": _str, "languages": _str, "background": _str, "living": _str,
        "people": {"type": ["array", "null"], "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "relation": {"type": "string"}, "notes": {"type": "string"}},
            "required": ["name", "relation", "notes"], "additionalProperties": False}},
        "wake_time": _str, "sleep_time": _str, "daily": _str, "interests": _str, "cheer_up": _str,
        "activities": _str, "health_notes": _str, "sensitive_topics": _str,
        "reminders": {"type": ["array", "null"], "items": {"type": "object", "properties": {
            "title": {"type": "string"},
            "kind": {"type": "string", "enum": ["medication", "task", "appointment", "call", "other"]},
            "time": _str, "days": {"type": "string"}},
            "required": ["title", "kind", "time", "days"], "additionalProperties": False}},
        "companion_name": _str,
        "skipped": {"type": "boolean"},
    },
    "required": ["preferred_name", "full_name", "pronouns", "age", "city", "languages", "background",
                 "living", "people", "wake_time", "sleep_time", "daily", "interests", "cheer_up",
                 "activities", "health_notes", "sensitive_topics", "reminders", "companion_name", "skipped"],
    "additionalProperties": False,
}

EXTRACT_PROMPT = """You turn an older person's spoken answer into profile fields for their companion app.
The question was: "{question}"
Fill only what the answer actually says; use null for missing text and [] for missing lists. Never guess.
- preferred_name: what they want to be called. pronouns: only if they clearly said it (else "unknown").
- city: where they live NOW (not where they grew up). background: their life story (where they grew up, work).
- people: relation "" if not said (never "unknown").
- living: who they live with, and where close family lives (e.g. "Lives alone; son Arjun lives in Pune").
- people: everyone they mention by name, with relation (e.g. "granddaughter") and short notes.
- wake_time / sleep_time: 24-hour "HH:MM". daily: their usual day in one or two sentences.
- interests, cheer_up, activities: short comma-separated phrases in their words.
- reminders: medicines or tasks they want reminders for, time as "HH:MM" (24h) or null, days "daily" or e.g. "mon,wed".
- companion_name: only for the question about the companion's name: the new name they chose, or the
  current name if they said it's fine. Otherwise null.
- sensitive_topics: anything they'd rather not discuss, with its context (e.g. "Her late husband, who passed away last year").
- skipped: true if they declined or said skip / don't know.
Write in third person where it's a description (e.g. background "Grew up in Madurai, retired maths teacher")."""


def _remaining(p: dict) -> list:
    return [k for k, _q, filled in TOPICS if not filled(p)]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def start() -> dict:
    p = profile_mod.load()
    remaining = _remaining(p)
    if not remaining:
        remaining = [k for k, _q, _f in TOPICS[1:]]  # profile complete: offer a refresh, minus the name
    oid = uuid.uuid4().hex
    state = {"remaining": remaining, "log": []}
    db.create_onboarding(oid, _now(), json.dumps(state))
    companion = profile_mod.companion_name(p)
    known = p["elder"]["preferred_name"]
    hello = (f"Hello{' ' + profile_mod.address_as(p) if known else ''}! I'm {companion}. I'll be checking in with "
             f"you every day, so I'd love to get to know you a little first. You can say skip to any question. ")
    text = hello + question(remaining[0], p)
    return {"onboarding_id": oid, "text": text, "audio_url": tts.speech_url(text, profile_mod.voice(p)),
            "total": len(remaining), "companion_name": companion}


def _combine(old: str, new: str | None) -> str:
    new = (new or "").strip()
    if not new:
        return old
    if not old or new.lower() in old.lower():
        return new if not old else old
    return f"{old}; {new}"


def merge(p: dict, patch: dict) -> tuple[dict, list]:
    """Merge an extracted patch into the profile. Returns (profile, list of 'what was learned' lines)."""
    learned = []
    e = p["elder"]
    if patch.get("preferred_name"):
        e["preferred_name"] = patch["preferred_name"].strip()
        learned.append(f"Name: {e['preferred_name']}")
    if patch.get("companion_name"):
        p["companion"]["name"] = patch["companion_name"].strip()[:40]
        learned.append(f"Companion's name: {p['companion']['name']}")
    if patch.get("pronouns") in ("she", "he", "they"):
        e["pronouns"] = patch["pronouns"]
    for key, label in (("full_name", "Full name"), ("age", "Age"), ("city", "City"), ("languages", "Languages"),
                       ("background", "Story"), ("living", "Living")):
        if patch.get(key):
            e[key] = _combine(e[key], patch[key])
            learned.append(f"{label}: {patch[key]}")
    names = {x["name"].lower(): x for x in p["people"]}
    for person in patch.get("people") or []:
        if not person["name"].strip():
            continue
        relation = (person.get("relation") or "").strip()
        person = {**person, "relation": "" if relation.lower() in ("unknown", "none", "n/a") else relation,
                  "notes": (person.get("notes") or "").strip()}
        existing = names.get(person["name"].lower())
        if existing:
            existing["relation"] = existing["relation"] or person["relation"]
            existing["notes"] = _combine(existing["notes"], person["notes"])
        else:
            entry = {"name": person["name"].strip(), "relation": person["relation"].strip(),
                     "notes": person["notes"].strip(), "birthday": ""}
            p["people"].append(entry)
            names[entry["name"].lower()] = entry
        learned.append(f"Person: {person['name']}" + (f" ({person['relation']})" if person["relation"] else ""))
    r = p["routine"]
    for key, label in (("wake_time", "Wakes up"), ("sleep_time", "Goes to bed")):
        if patch.get(key):
            r[key] = patch[key]
            learned.append(f"{label}: {patch[key]}")
    if patch.get("daily"):
        r["daily"] = _combine(r["daily"], patch["daily"])
        learned.append(f"Usual day: {patch['daily']}")
    for key, label in (("interests", "Enjoys"), ("cheer_up", "Cheers up with"), ("activities", "Activities"),
                       ("health_notes", "Health"), ("sensitive_topics", "Avoid")):
        if patch.get(key):
            p[key] = _combine(p[key], patch[key])
            learned.append(f"{label}: {patch[key]}")
    titles = {x["title"].lower() for x in p["reminders"]}
    for rem in patch.get("reminders") or []:
        if rem["title"].strip() and rem["title"].lower() not in titles:
            p["reminders"].append({"title": rem["title"].strip(), "kind": rem["kind"], "time": rem["time"],
                                   "days": rem["days"] or "daily", "notes": ""})
            titles.add(rem["title"].lower())
            learned.append(f"Reminder: {rem['title']}" + (f" at {rem['time']}" if rem["time"] else ""))
    return p, learned


def _extract(question: str, transcript: str) -> dict:
    # 20b at low effort: ~1 s and as accurate as 120b on single answers (120b took 1-9 s);
    # it runs alongside the reply so the person isn't kept waiting.
    return llm.complete_json([{"role": "system", "content": EXTRACT_PROMPT.format(question=question)},
                              {"role": "user", "content": transcript}], SCHEMA,
                             model=config.ONBOARDING_MODEL, effort="low")


def _reply(p: dict, question: str, transcript: str, next_question: str | None) -> str:
    companion, name = profile_mod.companion_name(p), profile_mod.address_as(p)
    system = (f"You are {companion}, a {profile_mod.STYLES[p['companion']['style']]} companion meeting "
              f"{name} for the first time to get to know them. Spoken conversation, in English: short, "
              "natural sentences, no lists or emojis. Never invent details.")
    if next_question:
        task = (f"You asked: \"{question}\". Reply in ONE short sentence that shows you listened (mention a "
                f"detail they said, or just say that's fine if they skipped). Then ask this next question in "
                f"your own words: \"{next_question}\"")
    else:
        task = (f"You asked: \"{question}\". Thank them warmly for sharing, say you'll remember all of this and "
                "that you'll check in every day. Two short sentences. No question.")
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"[Private note: {task}]\n{transcript}"}]
    try:
        return llm.tidy(llm.complete(messages))
    except Exception as exc:  # noqa: BLE001
        logger.warning("onboarding reply failed: %s", exc)
        return f"Thank you. {next_question}" if next_question else "Thank you so much. I'll talk to you every day."


def answer(oid: str, audio_path: str) -> dict:
    row = db.get_onboarding(oid)
    if row is None:
        raise OnboardingError("Unknown getting-to-know-you conversation.")
    if row["done"]:
        raise OnboardingError("This conversation has already finished.")
    state = json.loads(row["state_json"])
    topic = state["remaining"][0]
    p = profile_mod.load()
    asked = question(topic, p)
    try:
        waveform = audio.load_waveform(audio_path)
    except ValueError as exc:
        raise OnboardingError(f"Couldn't read the recording ({exc}).") from exc
    try:
        transcript = stt.transcribe(audio_path, audio.voice_quality(waveform) < 0.35)
    except Exception as exc:  # noqa: BLE001
        raise OnboardingError(f"Speech recognition failed: {exc}") from exc
    if not transcript:
        text = f"Sorry, I didn't catch that. {asked}"
        return {"heard": False, "transcript": "", "reply_text": text,
                "reply_audio_url": tts.speech_url(text, profile_mod.voice(p)), "done": False}

    next_topic = state["remaining"][1] if len(state["remaining"]) > 1 else None
    extraction = _pool.submit(_extract, asked, transcript)
    reply = _reply(p, asked, transcript, question(next_topic, p) if next_topic else None)
    try:
        patch = extraction.result() or {}
    except Exception as exc:  # noqa: BLE001 -- keep the conversation going; nothing learned this turn
        logger.warning("onboarding extraction failed: %s", exc)
        patch = {}
    p = profile_mod.load()  # fresh copy, then merge and save
    p, learned = merge(p, patch)
    p = profile_mod.save(p)

    state["remaining"] = state["remaining"][1:]
    state["log"].append({"topic": topic, "question": asked, "transcript": transcript,
                         "reply": reply, "learned": learned})
    done = not state["remaining"]
    db.update_onboarding(oid, json.dumps(state), done)
    return {"heard": True, "transcript": transcript, "reply_text": reply,
            "reply_audio_url": tts.speech_url(reply, profile_mod.voice(p)),
            "learned": learned, "skipped": bool(patch.get("skipped")), "topic": topic, "done": done,
            "progress": {"answered": len(state["log"]), "remaining": len(state["remaining"])},
            "companion_name": profile_mod.companion_name(p)}


def finish(oid: str) -> dict:
    row = db.get_onboarding(oid)
    if row is None:
        raise OnboardingError("Unknown getting-to-know-you conversation.")
    db.update_onboarding(oid, row["state_json"], True)
    return {"ok": True}
