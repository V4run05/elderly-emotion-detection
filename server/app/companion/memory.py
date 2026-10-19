"""Long-term memory: what the companion learns about the person, and what it recalls.

After each check-in ends, an LLM reads the conversation and returns (as strict JSON):
    memories        new facts: people and news about them, upcoming/recent events (dated),
                    preferences, ongoing health issues
    reminders_done  ids of today's reminders the person said they had done
    signals         wellbeing signals mentioned: sleep, appetite, pain, social contact, loneliness
    summary         one line, recalled at the next check-in ("Last time: ...")
This runs on a background thread, so the person never waits for it. Model: MEMORY_MODEL
(gpt-oss-120b: more faithful than 20b in testing, which invented a relationship).

Before each conversation, recall() picks what is worth bringing up: upcoming or just-passed
events, recent facts, the last few check-in summaries, and birthdays in the next week.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from app import config
from app.companion import profile as profile_mod
from app.companion import reminders as reminders_mod
from app.storage import db

logger = logging.getLogger("uvicorn.error")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")

SIGNAL_FIELDS = {"sleep": ["good", "poor", "unknown"], "appetite": ["good", "poor", "unknown"],
                 "pain": ["yes", "no", "unknown"], "social_contact": ["yes", "no", "unknown"],
                 "loneliness": ["yes", "no", "unknown"]}

SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["person", "event", "preference", "health", "fact"]},
                "text": {"type": "string"},
                "person": {"type": ["string", "null"]},
                "event_date": {"type": ["string", "null"]},
            },
            "required": ["kind", "text", "person", "event_date"], "additionalProperties": False}},
        "reminders_done": {"type": "array", "items": {"type": "integer"}},
        "signals": {"type": "object",
                    "properties": {k: {"type": "string", "enum": v} for k, v in SIGNAL_FIELDS.items()},
                    "required": list(SIGNAL_FIELDS), "additionalProperties": False},
        "summary": {"type": "string"},
    },
    "required": ["memories", "reminders_done", "signals", "summary"],
    "additionalProperties": False,
}


def _calendar(today: date) -> str:
    return ", ".join(f"{(today + timedelta(d)):%A} = {(today + timedelta(d)).isoformat()}"
                     for d in range(-1, 8))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _prompt(p: dict, today: date, todays_reminders: list, known: list) -> str:
    name = profile_mod.elder_name(p)
    rem = "; ".join(f"[{r['id']}] {reminders_mod.describe(r)}" for r in todays_reminders) or "(none)"
    mem = "\n".join(f"- {m['text']}" for m in known) or "(none)"
    people = ", ".join(f"{x['name']} ({x['relation']})" for x in p["people"]) or "(none listed)"
    return f"""You maintain the long-term memory of a companion app for an older person named {name}.
Today is {today:%A} {today.isoformat()}. Calendar: {_calendar(today)}.
People already known: {people}.

From the conversation, extract NEW things worth remembering for future chats: people in {name}'s life
and news about them, upcoming or recent events (with exact event_date resolved from the calendar),
{name}'s preferences and interests, ongoing health issues.
Rules:
- Only what {name} said. Ignore anything only the companion said or suggested.
- Short third-person facts, e.g. "Granddaughter Priya has her final exam on Friday 2026-10-23".
- Never invent relationships or details that weren't said.
- Skip anything already in the profile below or in the known memories.
- Do NOT store reminder/medication confirmations, greetings, or today's mood (other fields cover those).
- 0-5 items.
reminders_done: ids of today's reminders {name} clearly said were done. Today's reminders: {rem}
signals: sleep/appetite = good|poor|unknown; pain, loneliness = yes|no|unknown;
appetite = poor if they skip meals, eat very little, or don't feel like cooking or eating;
social_contact = yes if {name} talked to or met anyone since yesterday (calls, visitors and neighbours who
came by all count), no if they said they haven't, else unknown.
summary: one sentence the companion can recall next time.
Profile (already known):
{profile_mod.describe(p)}
Known memories:
{mem}"""


def extract(session_id: str) -> dict | None:
    """Reads a finished session and stores memories, reminder confirmations, summary, signals."""
    from app.dialogue import llm

    session = db.get_session(session_id)
    turns = db.get_turns(session_id)
    if not session or not turns:
        return None
    p = profile_mod.load()
    name, companion = profile_mod.elder_name(p), profile_mod.companion_name(p)
    now = datetime.now().astimezone()
    today = now.date()
    todays = reminders_mod.today(now)
    known = db.list_memories(limit=60)
    convo = f"{companion}: {session['greeting']}\n" + "\n".join(
        f"{name}: {t['transcript']}\n{companion}: {t['reply_text']}" for t in turns)

    result = llm.complete_json(
        [{"role": "system", "content": _prompt(p, today, todays, known)},
         {"role": "user", "content": convo}],
        SCHEMA, model=config.MEMORY_MODEL)

    existing = {_norm(m["text"]) for m in known}
    saved = 0
    for m in (result.get("memories") or [])[:5]:
        text = (m.get("text") or "").strip()
        if not text or _norm(text) in existing:
            continue
        ev = m.get("event_date")
        event_date = ev if ev and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev) else None
        db.add_memory(now.isoformat(timespec="seconds"), m.get("kind") or "fact", text, m.get("person"), event_date,
                      session_id, is_demo=bool(session["is_demo"]))
        existing.add(_norm(text))
        saved += 1
    valid_ids = {r["id"] for r in todays}
    for rid in result.get("reminders_done") or []:
        if rid in valid_ids:
            db.log_reminder(rid, today.isoformat(), "done", now.isoformat(timespec="seconds"), "conversation")
    db.update_session(session_id, summary=(result.get("summary") or "").strip()[:300], signals=result.get("signals") or {})
    logger.info("memory: session %s -> %d new memories, reminders done %s", session_id[:8], saved,
                result.get("reminders_done"))
    return result


def extract_in_background(session_id: str) -> None:
    def run():
        try:
            extract(session_id)
        except Exception as exc:  # noqa: BLE001 -- memory is best-effort
            logger.warning("memory extraction failed for %s: %s", session_id[:8], exc)
    _executor.submit(run)


def _birthdays(p: dict, today: date, days: int = 7) -> list:
    out = []
    for person in p["people"]:
        b = person.get("birthday", "")
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", b or "")
        if not m:
            continue
        for offset in range(days + 1):
            d = today + timedelta(offset)
            if d.day == int(m.group(1)) and d.month == int(m.group(2)):
                out.append({"name": person["name"], "relation": person["relation"], "date": d, "in_days": offset})
    return out


def recall(p: dict, today: date, exclude_session: str | None = None) -> dict:
    mems = db.list_memories(limit=300)
    upcoming, recent = [], []
    for m in mems:
        if m["event_date"]:
            d = date.fromisoformat(m["event_date"])
            if today - timedelta(1) <= d <= today + timedelta(7):
                upcoming.append({**m, "date": d})
            elif d < today - timedelta(3):
                continue  # old event, no longer worth raising
            else:
                recent.append(m)
        else:
            recent.append(m)
    upcoming.sort(key=lambda m: m["date"])
    summaries = [s for s in db.list_sessions(limit=20)
                 if s["summary"] and s["id"] != exclude_session][:3]
    return {"upcoming": upcoming[:6], "recent": recent[:12], "summaries": summaries,
            "birthdays": _birthdays(p, today)}


def _when(d: date, today: date) -> str:
    delta = (d - today).days
    rel = {-1: "yesterday", 0: "today", 1: "tomorrow"}.get(delta, f"in {delta} days" if delta > 0 else f"{-delta} days ago")
    return f"{d:%a %d %b} ({rel})"


def describe(r: dict, today: date) -> str:
    """Recall as plain text for the LLM's system prompt."""
    lines = []
    if r["upcoming"]:
        lines.append("Coming up / just happened:")
        lines += [f"- {_when(m['date'], today)}: {m['text']}" for m in r["upcoming"]]
    if r["birthdays"]:
        lines += [f"- {_when(b['date'], today)}: {b['name']}'s birthday ({b['relation']})" for b in r["birthdays"]]
    if r["recent"]:
        lines.append("Things you've learned in earlier chats:")
        lines += [f"- {m['text']}" for m in r["recent"]]
    if r["summaries"]:
        lines.append("Recent check-ins:")
        lines += [f"- {datetime.fromisoformat(s['started_at']):%a %d %b}: {s['summary']}" for s in r["summaries"]]
    return "\n".join(lines)
