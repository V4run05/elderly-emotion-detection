"""Fill the database with 14 days of SYNTHETIC check-in history so the family dashboard has a
trend to show in a demo. Every seeded session is marked is_demo=1 and the dashboard shows a
"demo data" badge while any exist. Today is left empty so a live check-in can be added on top.

    python scripts/seed_demo.py                 # "masked" scenario (default)
    python scripts/seed_demo.py --scenario healthy
    python scripts/seed_demo.py --scenario open  # openly low, no masking
    python scripts/seed_demo.py --clear          # remove demo data only
    python scripts/seed_demo.py --clear-all      # remove ALL check-ins (real ones too)

If no profile has been set up yet, a sample profile (Lakshmi, granddaughter Priya, ...) with two
reminders is created too, so the companion has something to be personal about. An existing
profile is never overwritten.

Scenarios:
    masked  - a week of genuinely good days, then a week of "I'm fine" while voice/face drop;
              yesterday is a full showcase conversation (SHOWCASE: masking, then Asha lifts her mood)
    healthy - says fine and seems fine throughout
    open    - says they're struggling and seems it (low, but not masked)
"""

import argparse
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.analysis import fusion, masking  # noqa: E402
from app.services.conversation import summarize  # noqa: E402
from app.storage import db  # noqa: E402

GOOD = [
    ("I went to the temple this morning, it was lovely and peaceful.", "That sounds so calming. Did you see anyone you know there?"),
    ("My granddaughter called yesterday, she got a new job!", "How wonderful, you must be so proud of her."),
    ("I made sambar for lunch and it came out perfectly.", "That sounds delicious. Did you use your mother's recipe?"),
    ("I'm doing well, I had a nice walk in the park.", "A walk sounds lovely. What was the weather like?"),
]
MASKED = [
    ("I'm fine. Nothing to worry about.", "I'm glad to hear it. It's alright to have quieter days too. How did you sleep last night?"),
    ("Oh, I'm okay. Same as always.", "That's alright. What did you have for breakfast today?"),
    ("I'm fine, just a bit tired.", "Tiredness can really weigh on you. Have you been able to rest?"),
    ("Can't complain. Don't worry about me.", "I always like hearing from you. Who have you talked to this week?"),
    ("I'm alright. I didn't do much today.", "Quiet days happen. Is there anything you've been missing doing?"),
]
OPEN = [
    ("I've been feeling very lonely since the children left.", "That sounds really hard. I'm glad you told me. When did you last talk with them?"),
    ("I don't feel like doing anything these days.", "That must be difficult. What's one small thing that used to cheer you up?"),
    ("I couldn't sleep again, I keep thinking about my husband.", "I'm so sorry. It's natural to miss him. Would you like to tell me about him?"),
]


# The "masked" scenario's last day (yesterday) is this full conversation instead of two random lines:
# she masks ("I'm fine"), opens up, and Asha lifts her mood by bringing back good things from her
# profile and memories (the roses, Priya, Kamala, teaching), checks her tablet and suggests a plan.
# (said, Asha's reply, words valence, voice/face valence). The voice values rise as she brightens, but
# the conversation as a whole still reads masked, so the alert story holds.
SHOWCASE_GREETING = "Good morning, {name}. How are you feeling today?"
SHOWCASE = [
    ("I'm fine. Nothing much to say today.",
     "That's alright, some mornings are quieter than others. Did you sleep well last night?", 0.45, -0.7),
    ("Not really. The house feels very quiet these days.",
     "I'm sorry, Lakshmi. A quiet house can feel heavy, and I'm glad you told me. "
     "Last week you said your roses had started blooming again. How are they doing?", -0.55, -0.75),
    ("Oh, the red one by the gate has three new buds now.",
     "Three new buds! All your care is paying off. Kamala would love to see them when she comes for tea.", 0.55, 0.1),
    ("Yes, she loves roses. I should call her.",
     "That sounds lovely. And Priya's exams are next week, aren't they? "
     "A message from her grandmother might be just what she needs.", 0.45, 0.15),
    ("She will be so nervous. I used to help her with her maths.",
     "She was lucky to have a maths teacher at home. Thirty five years of teaching shows. "
     "Before I forget, did you take your BP tablet after breakfast?", 0.2, 0.1),
    ("Yes, I took it with my coffee.",
     "Good. How about watering the roses this morning, and then calling Kamala over for tea?", 0.3, 0.15),
    ("Yes, I think I will. Thank you, Asha. I feel a bit better now.",
     "I'm really glad, Lakshmi. Enjoy the roses, and say hello to Kamala. I'm here whenever you want to talk.", 0.7, 0.25),
]
SHOWCASE_SUMMARY = "Said she was fine, then opened up about a quiet house. Cheered up talking about her roses and Priya."
SHOWCASE_SIGNALS = {"sleep": "poor", "appetite": "unknown", "pain": "unknown",
                    "social_contact": "unknown", "loneliness": "yes"}


def seed_showcase(day: date, rng: random.Random) -> None:
    started = datetime.combine(day, time(9, 12)).astimezone()
    session_id = uuid.uuid4().hex
    db.create_session(session_id, started.isoformat(timespec="seconds"),
                      SHOWCASE_GREETING.format(name=config.ELDER_NAME), is_demo=True, checkin=True)
    for i, (said, reply, verbal, nonverbal) in enumerate(SHOWCASE):
        at = (started + timedelta(seconds=40 * (i + 1))).isoformat(timespec="seconds")
        db.add_turn(session_id, i, at, said, reply, make_turn(said, verbal, nonverbal, rng),
                    context="wellbeing" if i == 0 else "chat")
    db.update_session(session_id, **summarize(db.get_turns(session_id)), summary=SHOWCASE_SUMMARY,
                      signals=SHOWCASE_SIGNALS,
                      ended_at=(started + timedelta(seconds=40 * len(SHOWCASE) + 30)).isoformat(timespec="seconds"))


def probs_for(valence: float) -> dict:
    """A plausible 4-class distribution whose valence is roughly `valence`."""
    if valence >= 0:
        h = min(0.9, 0.15 + valence * 0.8)
        p = {"Happiness": h, "Sadness": 0.05, "Anger": 0.03}
    else:
        s = min(0.9, 0.12 + -valence * 0.8)
        p = {"Sadness": s, "Happiness": 0.04, "Anger": 0.03}
    p["Neutral"] = max(0.0, 1.0 - sum(p.values()))
    return p


def channel(valence: float, quality: float) -> dict:
    p = probs_for(valence)
    label = max(p, key=p.get)
    return {"label": label, "confidence": p[label], "probs": p, "quality": quality}


def make_turn(transcript: str, verbal: float, nonverbal_target: float, rng: random.Random) -> dict:
    voice = channel(nonverbal_target + rng.uniform(-0.1, 0.1), rng.uniform(0.7, 1.0))
    face = channel(nonverbal_target + rng.uniform(-0.15, 0.15), rng.uniform(0.6, 1.0))
    face.update({"frames_used": 3, "frames_total": 3})
    fused = fusion.fuse({"voice": voice, "face": face})
    phrases = masking.find_reassurance(transcript)
    pos = max(0.0, verbal)
    neg = max(0.0, -verbal)
    sentiment = {"valence": verbal, "probs": {"positive": pos, "negative": neg,
                                              "neutral": 1 - pos - neg}}
    analysis = {"verbal": {**sentiment, "reassurance": phrases},
                "nonverbal": {**fused, "channels": {"voice": voice, "face": face}},
                **masking.analyse(verbal, fused["valence"], phrases), "safety_flag": False}
    return analysis


def day_plan(scenario: str, day_index: int, rng: random.Random):
    """(lines, verbal valence, non-verbal valence) for day_index 0 (oldest) .. 13."""
    if scenario == "healthy" or (scenario == "masked" and day_index < 7):
        return GOOD, rng.uniform(0.55, 0.85), rng.uniform(0.15, 0.45)
    if scenario == "masked":
        decline = (day_index - 7) / 6  # gets gradually lower over the second week
        return MASKED, rng.uniform(0.35, 0.7), -0.25 - 0.4 * decline + rng.uniform(-0.08, 0.05)
    return OPEN, rng.uniform(-0.8, -0.45), rng.uniform(-0.65, -0.3)


def seed(scenario: str) -> int:
    rng = random.Random(42)
    today = date.today()
    count = 0
    for day_index in range(14):
        day = today - timedelta(days=14 - day_index)
        if day_index == 4:
            continue  # one missed day, for realism
        if scenario == "masked" and day_index == 13:
            seed_showcase(day, rng)
            count += 1
            continue
        lines, verbal, nonverbal = day_plan(scenario, day_index, rng)
        started = datetime.combine(day, time(9, rng.randint(0, 50))).astimezone()
        session_id = uuid.uuid4().hex
        db.create_session(session_id, started.isoformat(timespec="seconds"),
                          f"Good morning, {config.ELDER_NAME}! How are you feeling today?",
                          is_demo=True, checkin=True)
        picks = rng.sample(lines, k=min(2, len(lines)))
        for i, (said, reply) in enumerate(picks):
            analysis = make_turn(said, verbal, nonverbal, rng)
            at = (started + timedelta(minutes=i + 1)).isoformat(timespec="seconds")
            db.add_turn(session_id, i, at, said, reply, analysis, context="wellbeing" if i == 0 else "chat")
        summary = summarize(db.get_turns(session_id))
        low_day = nonverbal <= -0.25
        signals = {"sleep": "poor" if low_day and rng.random() < 0.6 else rng.choice(["good", "unknown"]),
                   "appetite": "poor" if low_day and rng.random() < 0.3 else "unknown",
                   "pain": "yes" if rng.random() < 0.2 else "unknown",
                   "social_contact": "no" if low_day and rng.random() < 0.5 else rng.choice(["yes", "unknown"]),
                   "loneliness": "yes" if low_day and rng.random() < 0.3 else "unknown"}
        db.update_session(session_id, **summary, summary=f"{config.ELDER_NAME} said “{picks[0][0]}”", signals=signals,
                          ended_at=(started + timedelta(minutes=3)).isoformat(timespec="seconds"))
        count += 1
    return count


SAMPLE_PROFILE = {
    "elder": {"full_name": "Lakshmi Iyer", "preferred_name": "Lakshmi", "pronouns": "she", "age": "78",
              "city": "Chennai", "languages": "Tamil, English",
              "background": "Retired maths teacher, taught for 35 years. Grew up in Madurai.",
              "living": "Lives alone since her husband passed. Her son Arjun lives in Pune."},
    "people": [
        {"name": "Priya", "relation": "granddaughter", "notes": "Studies engineering in Bangalore, calls on Sundays", "birthday": ""},
        {"name": "Arjun", "relation": "son", "notes": "Lives in Pune with his family", "birthday": ""},
        {"name": "Kamala", "relation": "neighbour and friend", "notes": "Comes over for tea", "birthday": ""},
    ],
    "routine": {"wake_time": "06:00", "sleep_time": "21:30",
                "daily": "Morning walk in the park, temple on Tuesdays, watches her serial at 8 pm"},
    "interests": "Gardening (roses), old Tamil film songs, cooking, crosswords",
    "cheer_up": "Talking about her grandchildren, her garden, singing M.S. Subbulakshmi songs",
    "activities": "A short walk, watering the plants, calling Kamala, a crossword",
    "health_notes": "Knee pain in cold weather. Diabetic.",
    "sensitive_topics": "Her late husband Raman: let her bring him up",
    "companion": {"name": "Asha", "voice": "en-IN-NeerjaNeural", "style": "warm", "address_as": "Lakshmi Amma"},
    "family_contact": {"name": "Arjun", "relation": "son"},
    "reminders": [{"title": "BP tablet after breakfast", "kind": "medication", "time": "09:00", "days": "daily"},
                  {"title": "Evening walk", "kind": "task", "time": "17:30", "days": "daily"}],
}
DEMO_MEMORIES = [
    ("person", "Priya has her engineering exams next week", "Priya", 3),
    ("preference", "Lakshmi's roses have started blooming again", None, None),
    ("health", "Lakshmi's knee has been hurting in the mornings", None, None),
    ("preference", "The red rose by the gate has three new buds", None, None),
    ("person", "Lakshmi used to help Priya with her maths", "Priya", None),
    ("event", "Lakshmi plans to invite Kamala over to see the roses", "Kamala", None),
]


def seed_extras() -> list:
    from app.companion import profile as profile_mod
    done = []
    if db.get_profile() is None:
        profile_mod.save(SAMPLE_PROFILE)
        done.append("sample profile (Lakshmi) with 2 reminders")
    now = datetime.now().astimezone()
    for kind, text, person, in_days in DEMO_MEMORIES:
        event = (date.today() + timedelta(days=in_days)).isoformat() if in_days else None
        db.add_memory(now.isoformat(timespec="seconds"), kind, text, person, event, None, is_demo=True)
    done.append(f"{len(DEMO_MEMORIES)} demo memories")
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=["masked", "healthy", "open"], default="masked")
    parser.add_argument("--clear", action="store_true", help="remove demo data and exit")
    parser.add_argument("--clear-all", action="store_true", help="remove ALL check-ins and exit")
    args = parser.parse_args()

    db.init()
    if args.clear_all:
        print(f"Deleted {db.delete_sessions()} check-ins (all).")
        return
    removed = db.delete_sessions(demo_only=True)
    if args.clear:
        print(f"Deleted {removed} demo check-ins.")
        return
    print(f"Replaced {removed} old demo check-ins with {seed(args.scenario)} new ones "
          f"('{args.scenario}' scenario).")
    print("Also added: " + ", ".join(seed_extras()) + ". Open /dashboard to see them.")


if __name__ == "__main__":
    main()
