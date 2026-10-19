from datetime import date, datetime

import pytest

from app.analysis import baseline, masking


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    from app import config
    from app.storage import db
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init()
    return db


def sessions(values):
    return [{"started_at": f"2026-10-{i + 1:02d}T09:00:00+05:30", "nonverbal_valence": v}
            for i, v in enumerate(values)]


# ---------------------------------------------------------------- baseline
def test_baseline_not_ready_uses_fixed_line():
    b = baseline.compute(sessions([0.0, 0.0]))
    assert not b["ready"] and b["low_threshold"] == -0.20


def test_baseline_for_person_who_reads_sad():
    b = baseline.compute(sessions([-0.30, -0.28, -0.35, -0.31, -0.29, 0.9]))  # 6th ignored
    assert b["ready"] and b["normal"] == -0.30
    assert b["low_threshold"] < -0.40
    # their normal day is no longer "low" ...
    assert masking.classify(0.6, -0.30, True, b["low_threshold"]) == "ok"
    # ... but a real drop still is
    assert masking.classify(0.6, -0.60, True, b["low_threshold"]) == "masked"


def test_baseline_for_flat_person_catches_smaller_drop():
    b = baseline.compute(sessions([0.0, 0.02, -0.02, 0.01, -0.01]))
    assert -0.20 < b["low_threshold"] < -0.10
    assert masking.classify(0.6, -0.15, True) == "ok"                    # fixed line misses it
    assert masking.classify(0.6, -0.15, True, b["low_threshold"]) == "masked"


def test_baseline_never_calls_positive_low():
    b = baseline.compute(sessions([0.6, 0.62, 0.58, 0.61, 0.6]))
    assert b["low_threshold"] <= 0.0


# ---------------------------------------------------------------- reminders
def test_reminder_schedule_and_status(temp_db):
    from app.companion import reminders
    temp_db.add_reminder("BP tablet", "medication", "09:00", "daily", "", "setup", "x")
    temp_db.add_reminder("Temple", "task", "17:00", "tue", "", "setup", "x")
    temp_db.add_reminder("Doctor", "appointment", "11:00", "once:2026-10-20", "", "family", "x")
    monday_morning = datetime(2026, 10, 19, 9, 30).astimezone()
    items = reminders.today(monday_morning)
    assert [r["title"] for r in items] == ["BP tablet"]
    assert items[0]["status"] == "due"
    assert reminders.to_mention(monday_morning)["title"] == "BP tablet"
    tuesday = datetime(2026, 10, 20, 10, 30).astimezone()
    assert {r["title"]: r["status"] for r in reminders.today(tuesday)} == {
        "BP tablet": "due", "Doctor": "soon", "Temple": "later"}
    temp_db.log_reminder(1, "2026-10-20", "done", "x", "conversation")
    assert reminders.to_mention(tuesday)["title"] == "Doctor"


# ---------------------------------------------------------------- profile + plan
def test_profile_normalize_and_describe():
    from app.companion import profile
    p = profile.normalize({"elder": {"preferred_name": "  Lakshmi ", "pronouns": "xyz"},
                           "people": [{"name": "Priya", "relation": "granddaughter"}, {"name": ""}],
                           "companion": {"style": "loud"},
                           "reminders": [{"title": "BP tablet", "time": "09:00"}, {"title": ""}]})
    assert p["elder"]["preferred_name"] == "Lakshmi" and p["elder"]["pronouns"] == "they"
    assert len(p["people"]) == 1 and p["companion"]["style"] == "warm"
    assert p["reminders"] == [{"title": "BP tablet", "kind": "task", "time": "09:00",
                               "days": "daily", "notes": ""}]
    text = profile.describe(p)
    assert "Priya (granddaughter)" in text


def test_plan_hints_are_situational(temp_db):
    from app.companion import plan, profile
    temp_db.add_reminder("BP tablet", "medication", "09:00", "daily", "", "setup", "x")
    p = profile.normalize({"elder": {"preferred_name": "Lakshmi"}, "cheer_up": "singing old songs",
                           "people": [{"name": "Priya", "relation": "granddaughter"}]})
    recall = {"upcoming": [{"text": "Kamala is coming for tea today", "date": date(2026, 10, 19)}],
              "recent": [], "summaries": [], "birthdays": []}
    now = datetime(2026, 10, 19, 10, 0).astimezone()
    early = " ".join(plan.hints(p, recall, ["Good morning!"], ["Good morning!"], False, now))
    assert "Kamala" in early and "BP tablet" in early and "singing" not in early
    # the reminder was already raised in an earlier conversation today -> not again
    later = plan.hints(p, recall, ["hi"], ["Have you taken your BP tablet?", "Kamala tea today?"], False, now)
    assert later == []
    assert "singing old songs" in " ".join(plan.hints(p, recall, ["a", "b", "c"], [], True, now))


def turn(status, suggested=False, input_kind="voice"):
    return {"status": status, "input": input_kind, "analysis": {"support_suggested": suggested}}


def test_support_only_when_needed():
    from app.companion import plan
    # one noisy "low" reading in ordinary chat: just chat
    assert plan.support([turn("ok"), turn("ok")], "low", 0.0, False, True) == {"mode": None, "suggest": False}
    sad = "I miss my husband. I feel very alone."
    # clearly upset words: listen first (no suggestion yet)
    assert plan.support([], "ok", -0.8, False, True, sad) == {"mode": "distress", "suggest": False}
    # still upset on the next message: now a suggestion may help
    prev = {"status": "low", "input": "voice", "analysis": {"support": "distress", "support_suggested": False}}
    assert plan.support([prev], "ok", -0.8, False, True, sad) == {"mode": "distress", "suggest": True}
    # negative but not emotional ("Oh no, I forgot my tablet") is not distress
    assert plan.support([], "ok", -0.9, False, True, "Oh no, I forgot my tablet.")["mode"] is None
    # the daily answer reads masked: be gentle, but no suggestion
    assert plan.support([], "masked", 0.6, True, True) == {"mode": "daily", "suggest": False}
    # all of the last four spoken messages low
    assert plan.support([turn("low"), turn("masked"), turn("low")], "low", 0.0, False, True)["mode"] == "sustained"
    assert plan.support([turn("low"), turn("masked")], "low", 0.0, False, True)["mode"] is None
    # typed messages don't count towards "sustained"
    assert plan.support([turn("low", input_kind="typed"), turn("low", input_kind="typed")], "ok", 0.0,
                        False, False)["mode"] is None
    # support suggested recently: still gentle (mode) but no new suggestion
    prev = {"status": "low", "input": "voice", "analysis": {"support": "distress", "support_suggested": True}}
    assert plan.support([prev], "low", -0.9, False, True, sad) == {"mode": "distress", "suggest": False}


def test_conversation_summary_uses_daily_answer_and_spoken_messages():
    from app.services.conversation import summarize

    def turn(verbal, nonverbal, context="chat", input_kind="voice", available=True, phrases=()):
        return {"verbal_valence": verbal, "nonverbal_valence": nonverbal, "context": context,
                "input": input_kind, "safety_flag": 0,
                "analysis": {"verbal": {"reassurance": list(phrases)}, "nonverbal": {"available": available}}}
    turns = [turn(0.7, -0.5, "wellbeing", phrases=["I'm fine"]),   # the daily answer
             turn(-0.4, -0.3),                                    # chat about a sad film
             turn(0.9, 0.0, input_kind="typed", available=False)]  # typed: no seemed
    s = summarize(turns)
    assert s["verbal_valence"] == 0.7                 # "said" = the daily answer
    assert s["nonverbal_valence"] == -0.4             # "seemed" = mean of the two spoken messages
    assert s["status"] == "masked"
    typed_only = summarize([turn(0.5, 0.0, input_kind="typed", available=False)])
    assert typed_only["nonverbal_valence"] is None


# ---------------------------------------------------------------- memory
def test_memory_extract_stores_results(temp_db, monkeypatch):
    from app.companion import memory
    from app.dialogue import llm
    rid = temp_db.add_reminder("BP tablet", "medication", "09:00", "daily", "", "setup", "x")
    temp_db.create_session("s1", "2026-10-19T09:00:00+05:30", "Good morning!")
    analysis = {"verbal": {"valence": 0.5, "reassurance": []}, "nonverbal": {"valence": 0.0},
                "masking_score": 0.2, "status": "ok", "safety_flag": False}
    temp_db.add_turn("s1", 0, "2026-10-19T09:01:00+05:30", "Priya's exam is on Friday. I took my tablet.",
                     "Good luck to her!", analysis)
    fake = {"memories": [{"kind": "event", "text": "Priya's exam is on Friday 2026-10-23",
                          "person": "Priya", "event_date": "2026-10-23"},
                         {"kind": "event", "text": "bad date", "person": None, "event_date": "Friday"}],
            "reminders_done": [rid, 999],
            "signals": {"sleep": "poor", "appetite": "unknown", "pain": "no",
                        "social_contact": "yes", "loneliness": "unknown"},
            "summary": "Talked about Priya's exam."}
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: fake)
    memory.extract("s1")
    mems = temp_db.list_memories()
    assert {m["text"] for m in mems} == {"Priya's exam is on Friday 2026-10-23", "bad date"}
    assert next(m for m in mems if m["text"] == "bad date")["event_date"] is None
    today = datetime.now().date().isoformat()
    assert temp_db.reminder_log_for(today)[rid]["source"] == "conversation"
    s = temp_db.get_session("s1")
    assert s["summary"] == "Talked about Priya's exam." and s["signals"]["sleep"] == "poor"
    memory.extract("s1")  # running again must not duplicate memories
    assert len(temp_db.list_memories()) == 2


def test_spoken_time():
    from app.companion.reminders import spoken_time
    assert spoken_time("17:30") == "5:30 pm"
    assert spoken_time("09:00") == "9 am"
    assert spoken_time("00:15") == "12:15 am"
    assert spoken_time("12:00") == "12 pm"


def test_greeting_hook_only_uses_real_timely_memories():
    from app.companion import plan
    today = date(2026, 10, 19)
    empty = {"upcoming": [], "recent": [{"text": "likes roses"}], "summaries": [], "birthdays": []}
    assert plan.greeting_hook(empty, today) is None   # nothing timely -> mention nothing
    rec = {**empty, "upcoming": [{"text": "Kamala is coming for tea", "date": date(2026, 10, 19)}]}
    assert plan.greeting_hook(rec, today) == "Kamala is coming for tea (today)"
    rec = {**empty, "upcoming": [{"text": "Priya's exam", "date": date(2026, 10, 23)}]}
    assert plan.greeting_hook(rec, today) is None     # 4 days away: not a greeting topic


def test_onboarding_can_rename_the_companion():
    from app.companion import onboarding, profile
    p = profile.normalize({})
    assert "{companion}" not in onboarding.question("companion", p)
    p, learned = onboarding.merge(p, {"companion_name": "Meera"})
    assert p["companion"]["name"] == "Meera" and "Companion's name: Meera" in learned


def test_onboarding_merge_dedupes_and_combines():
    from app.companion import onboarding, profile
    p = profile.normalize({"people": [{"name": "Priya", "relation": "granddaughter"}], "interests": "gardening"})
    p, learned = onboarding.merge(p, {"people": [{"name": "priya", "relation": "", "notes": "calls on Sundays"},
                                                  {"name": "Kamala", "relation": "neighbour", "notes": ""}],
                                      "interests": "old Tamil songs", "reminders": [],
                                      "pronouns": "unknown", "wake_time": "06:00"})
    assert [x["name"] for x in p["people"]] == ["Priya", "Kamala"]
    assert p["people"][0]["notes"] == "calls on Sundays" and p["people"][0]["relation"] == "granddaughter"
    assert p["interests"] == "gardening; old Tamil songs"
    assert p["elder"]["pronouns"] == "they" and p["routine"]["wake_time"] == "06:00"
    assert "Person: Kamala (neighbour)" in learned
