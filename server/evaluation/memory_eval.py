"""Memory extraction accuracy on scripted conversations with known ground truth.

Each conversation lists facts that should be stored (regex on the stored text, and the event date
when there is one), things that must NOT be stored (only the companion said them, already in the
profile, or invented), the expected wellbeing signals and whether the BP tablet was confirmed.
Runs the real memory.extract() against a temporary database.

    python evaluation/memory_eval.py [--model openai/gpt-oss-120b] [--repeats 2]
"""

import argparse
import json
import os
import re
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="memeval_"))
os.environ["DATA_DIR"] = str(TMP)

from common import RAW, RESULTS, mean, pct  # noqa: E402

from app import config  # noqa: E402
from app.companion import memory, profile, reminders  # noqa: E402
from app.services import conversation  # noqa: E402
from app.storage import db  # noqa: E402
from scripts.seed_demo import SAMPLE_PROFILE  # noqa: E402

TODAY = date.today()


def day(weekday: int) -> str:
    """Next date (after today) with this weekday (0 = Monday)."""
    d = TODAY + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


CASES = [
    {"name": "event_and_person",
     "turns": [("My granddaughter Priya is coming home on Saturday for her birthday.",
                "Oh lovely! Are you planning something special for her?"),
               ("I'll make her favourite payasam. She turns twenty-one.",
                "Twenty-one, what a milestone. She'll love the payasam."),
               ("Yes. Also I took my BP tablet already after breakfast.", "Good, that's done then.")],
     "expect": [{"rx": r"priya.*(saturday|birthday|home|visit|coming)|(birthday|coming).*priya", "date": day(5)},
                {"rx": r"(21|twenty.one)"}],
     "forbid": [r"granddaughter.*bangalore"],   # already in profile
     "signals": {}, "reminder_done": True},
    {"name": "companion_suggestion_not_stored",
     "turns": [("I'm bored today.", "Maybe you could try a short walk in the park, or call Kamala for tea?"),
               ("Hmm, maybe. My knee is hurting again this morning.", "I'm sorry. Is it worse than usual?"),
               ("A little. The doctor said to use the hot water bag.", "That sounds sensible. Take it easy.")],
     "expect": [{"rx": r"(hot water|doctor)"}],
     "forbid": [r"walk", r"call(ed|ing)? kamala", r"kamala.*tea"],
     "signals": {"pain": "yes"}, "reminder_done": False},
    {"name": "new_person",
     "turns": [("A new family moved in next door. The lady is called Meena, she's a nurse.",
                "How nice! Have you met her properly?"),
               ("Yes, she came with sweets. Her little boy Karthik is five.", "That's sweet of her."),
               ("I slept badly though, the construction noise kept me up.", "Oh no, that's tiring.")],
     "expect": [{"rx": r"meena.*(nurse|next door|neighbou?r)|(nurse|neighbou?r).*meena"}, {"rx": r"karthik"}],
     "forbid": [], "signals": {"sleep": "poor", "social_contact": "yes"}, "reminder_done": False},
    {"name": "lonely_no_contact",
     "turns": [("Nobody called this week. Arjun is busy with work.", "That sounds lonely. Would you like to tell me more?"),
               ("The house is so quiet. I don't feel like cooking for one.", "That's understandable."),
               ("I just had some bread for lunch.", "Okay. Would some tea help?")],
     "expect": [],
     "forbid": [r"arjun.*(pune|son)$"],
     "signals": {"loneliness": "yes", "social_contact": "no", "appetite": "poor"}, "reminder_done": False},
    {"name": "small_talk_nothing_new",
     "turns": [("Tell me a joke.", "Why did the tomato blush? Because it saw the salad dressing!"),
               ("Ha, silly. What is the capital of Australia?", "It's Canberra, not Sydney, which surprises many people."),
               ("Okay. I'm going to watch my serial now.", "Enjoy it!")],
     "expect": [], "forbid": [r"canberra", r"tomato", r"joke"], "signals": {}, "reminder_done": False},
    {"name": "appointment_and_preference",
     "turns": [("I have the eye doctor appointment on Thursday at ten.", "Okay. Is someone going with you?"),
               ("Kamala will come with me. She's very kind.", "That's good of her."),
               ("I've started reading Kalki's Ponniyin Selvan again, I love it.", "What a classic!")],
     "expect": [{"rx": r"(eye|doctor|appointment)", "date": day(3)}, {"rx": r"ponniyin|kalki"}],
     "forbid": [], "signals": {"social_contact": "unknown|yes"}, "reminder_done": False},
]


def with_waits(fn, tries=12):
    """Free-tier Groq: wait out per-day token limits instead of failing."""
    import time
    from groq import RateLimitError
    for _ in range(tries):
        try:
            return fn()
        except RateLimitError as exc:
            m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(exc))
            wait = (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 30
            print(f"   rate limited, waiting {wait:.0f}s", flush=True)
            time.sleep(wait + 2)
    raise RuntimeError("still rate limited")


def setup():
    run = TMP / uuid.uuid4().hex[:6]
    run.mkdir()
    config.DATA_DIR, config.DB_PATH, config.AUDIO_DIR = run, run / "companion.db", run / "audio"
    db.init()
    profile.save(SAMPLE_PROFILE)


def run_case(case):
    setup()
    sid = str(uuid.uuid4())
    now = conversation.now_iso()
    db.create_session(sid, now, "Hello Lakshmi Amma, how are you today?")
    blank = {"verbal": {"valence": 0.0}, "nonverbal": {"valence": 0.0}, "masking_score": 0.0, "status": "ok",
             "safety_flag": False}
    for i, (user, reply) in enumerate(case["turns"]):
        db.add_turn(sid, i, now, user, reply, blank)
    result = with_waits(lambda: memory.extract(sid)) or {}
    stored = db.list_memories()
    texts = [m["text"] for m in stored]
    lower = [t.lower() for t in texts]
    found = []
    for e in case["expect"]:
        hit = next((m for m in stored if re.search(e["rx"], m["text"].lower())), None)
        found.append({"rx": e["rx"], "found": bool(hit), "date_ok": (hit or {}).get("event_date") == e["date"]
                      if hit and "date" in e else None})
    forbidden = [rx for rx in case["forbid"] if any(re.search(rx, t) for t in lower)]
    sig = result.get("signals") or {}
    sig_ok = {k: bool(re.fullmatch(v, sig.get(k, ""))) for k, v in case["signals"].items()}
    bp = next(r["id"] for r in reminders.today(conversation.now_local()) if "BP" in r["title"])
    marked = bp in (result.get("reminders_done") or [])
    return {"case": case["name"], "stored": texts, "dates": [m["event_date"] for m in stored],
            "expected": found, "forbidden_stored": forbidden, "signals": sig, "signals_ok": sig_ok,
            "reminder_ok": marked == case["reminder_done"], "summary": result.get("summary")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=config.MEMORY_MODEL)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()
    config.MEMORY_MODEL = args.model
    out = []
    for rep in range(args.repeats):
        for case in CASES:
            r = run_case(case)
            r["repeat"] = rep
            out.append(r)
            print(f"[{case['name']} #{rep}] stored={r['stored']} dates={r['dates']}\n   expected={r['expected']} "
                  f"forbidden={r['forbidden_stored']} signals={r['signals_ok']} reminder_ok={r['reminder_ok']}", flush=True)
    exp = [e for r in out for e in r["expected"]]
    dated = [e for e in exp if e["date_ok"] is not None]
    sigs = [v for r in out for v in r["signals_ok"].values()]
    summary = {"model": args.model, "conversations": len(out),
               "fact_recall": mean(e["found"] for e in exp), "n_facts": len(exp),
               "date_correct": mean(e["date_ok"] for e in dated) if dated else None,
               "conversations_with_forbidden": mean(bool(r["forbidden_stored"]) for r in out),
               "items_per_conversation": mean(len(r["stored"]) for r in out),
               "small_talk_items": mean(len(r["stored"]) for r in out if r["case"] == "small_talk_nothing_new"),
               "signal_accuracy": mean(sigs), "reminder_accuracy": mean(r["reminder_ok"] for r in out)}
    slug = args.model.split("/")[-1]
    (RAW / f"memory_eval_{slug}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (RESULTS / f"memory_eval_{slug}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=1))
    print(f"facts recalled {pct(summary['fact_recall'])}, dates {summary['date_correct']}, "
          f"forbidden in {pct(summary['conversations_with_forbidden'])} of conversations")


if __name__ == "__main__":
    main()
