"""Tests for the changes made after the evaluation (docs/EVALUATION.md §8)."""

import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

import pytest

from app import config
from app.analysis import baseline, masking, safety, trends
from app.companion import profile
from scripts.seed_demo import SAMPLE_PROFILE


@pytest.fixture(autouse=True)
def _five_calibration_sessions(monkeypatch):
    monkeypatch.setattr(config, "BASELINE_SESSIONS", 5)


# ---------------------------------------------------------------- words side
def test_indian_english_reassurance():
    assert masking.find_reassurance("Okay only, what to say.")
    assert masking.find_reassurance("I'm managing somehow.")
    assert not masking.find_reassurance("I'm managing the house accounts for Kamala.")


def test_but_clause_is_opening_up():
    assert masking.after_contrast("I'm fine, but I miss him.") == "I miss him."
    assert masking.after_contrast("It's alright, though the nights are hard.") == "the nights are hard."
    assert masking.after_contrast("I'm fine, just a bit tired.") == "a bit tired."
    assert masking.after_contrast("I went out but it rained.") is None       # no reassurance before "but"


def test_verbal_reading_uses_the_part_after_but(monkeypatch):
    from app.services import conversation
    vals = {"I'm fine, but I miss him.": 0.4, "I miss him.": -0.7}
    monkeypatch.setattr(conversation.text, "predict", lambda t: {"valence": vals[t]})
    sentiment, phrases = conversation.verbal_reading("I'm fine, but I miss him.")
    assert sentiment["valence"] == -0.7 and phrases == []
    # "miss" is an emotion word: opening up even though the model reads "I miss him" as neutral
    vals.update({"I'm fine, but I miss him.": 0.4, "I miss him.": 0.04})
    sentiment, phrases = conversation.verbal_reading("I'm fine, but I miss him.")
    assert sentiment["valence"] <= config.NEGATIVE_VERBAL_THRESHOLD and phrases == []
    # mild minimising stays a reassurance (masking)
    vals.update({"I'm alright, just a bit tired.": 0.22, "a bit tired.": -0.29})
    sentiment, phrases = conversation.verbal_reading("I'm alright, just a bit tired.")
    assert sentiment["valence"] == 0.22 and phrases


# ---------------------------------------------------------------- safety
@pytest.mark.parametrize("text", [
    "I just want to go to sleep and not wake up.", "I'm tired of living.", "I can't go on like this.",
    "I wish I were dead.", "I've been thinking about ending my life."])
def test_keyword_screen_catches_common_phrasings(text):
    assert safety.keyword_flag(text)


@pytest.mark.parametrize("text", ["I'm dying to see my grandchildren.", "This heat is killing me.",
                                  "I can't go on the trip next week.", "I'm so tired today."])
def test_keyword_screen_ignores_idioms(text):
    assert not safety.keyword_flag(text)


def test_llm_screen_falls_back_and_never_raises(monkeypatch):
    monkeypatch.setattr(__import__("app.dialogue.llm", fromlist=["x"]), "_cooldown", {})
    from app.dialogue import llm
    monkeypatch.setattr(config, "GROQ_API_KEY", "x")
    calls = []

    def fake(messages, model=None, **kw):
        calls.append(model)
        if model == config.SAFETY_SCREEN_MODEL:
            raise RuntimeError("rate limited")
        return '{"risk": true}'
    monkeypatch.setattr(llm, "complete", fake)
    assert safety.llm_flag("I keep thinking about joining him.", ["It reminds me of Raman."]) == \
        (True, config.SAFETY_SCREEN_FALLBACKS[0])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert safety.llm_flag("anything") == (None, None)


def test_safety_reply_is_fixed_and_gives_the_helpline():
    from app.dialogue import llm
    p = profile.normalize(SAMPLE_PROFILE)
    first = llm.safety_reply(p, first=True)
    assert "Arjun" in first and config.HELPLINE_NAME in first and "1 4 4 1 6" in first
    assert llm.safety_reply(p, first=False) != first
    ask = llm.safety_reply(p, first=True, ask=True)
    assert "not wanting to live" in ask and "1 4 4 1 6" not in ask


# ---------------------------------------------------------------- LLM resilience
def test_rate_limited_model_goes_on_cooldown_and_chain_moves_on(monkeypatch):
    from app.dialogue import llm
    monkeypatch.setattr(llm, "_cooldown", {})
    monkeypatch.setattr(config, "LLM_BACKUP_MODELS", ["backup"])

    class FakeRateLimit(Exception):
        pass
    exc = FakeRateLimit("Rate limit reached on tokens per day (TPD). Please try again in 8m27.1s.")
    assert llm._rate_limit_wait(exc) == pytest.approx(507.1)
    llm._cooldown[config.LLM_MODEL] = time.monotonic() + 500
    assert llm.chain() == [config.LLM_FAST_MODEL, "backup"]
    assert llm.status()["degraded"] is True

    def fake(messages, model=None, **kw):
        if model == config.LLM_FAST_MODEL:
            raise RuntimeError("also down")
        return f"from {model}"
    monkeypatch.setattr(llm, "complete", fake)
    assert llm.hedged([]) == ("from backup", "backup")


def test_nothing_available_gives_an_honest_reply(monkeypatch):
    from app.dialogue import llm
    monkeypatch.setattr(llm, "_cooldown", {})
    monkeypatch.setattr(llm, "chain", lambda: [])
    p = profile.normalize({})
    text = llm.reply(p, "", [], "Hello", "ok", {"mode": None, "suggest": False}, [], False, datetime.now())
    assert text == llm.UNAVAILABLE_REPLY and "catch" not in text


def test_fast_model_not_called_when_primary_is_quick(monkeypatch):
    from app.dialogue import llm
    monkeypatch.setattr(llm, "_cooldown", {})
    used = []

    def fake(messages, model=None, **kw):
        used.append(model)
        return "quick"
    monkeypatch.setattr(llm, "complete", fake)
    assert llm.hedged([]) == ("quick", config.LLM_MODEL)
    assert used == [config.LLM_MODEL]          # no second request: half the tokens


# ---------------------------------------------------------------- sensitive topics
def test_sensitive_names_hidden_until_they_bring_it_up():
    p = profile.normalize(SAMPLE_PROFILE)
    assert profile.sensitive_names(p) == {"Raman"}
    closed = profile.describe(p, sensitive_open=False)
    assert "Raman" not in closed and "Never bring up death" in closed
    assert "Raman" in profile.describe(p, sensitive_open=True)
    assert not profile.sensitive_opened(p, ["The roses are lovely today."])
    assert profile.sensitive_opened(p, ["I miss my husband so much."])
    assert profile.sensitive_opened(p, ["Raman used to sit here."])


# ---------------------------------------------------------------- per-channel baseline
def _sessions(voice_vals, face_vals):
    return [{"started_at": f"2026-10-{i + 1:02d}T09:00:00+05:30", "nonverbal_valence": 0.0,
             "voice_valence": v, "face_valence": f} for i, (v, f) in enumerate(zip(voice_vals, face_vals))]


def test_per_channel_baseline_and_camera_off():
    b = baseline.compute(_sessions([-0.35, -0.30, -0.33, -0.36, -0.31], [0.40, 0.35, 0.45, 0.38, 0.42]))
    assert b["mode"] == "channels" and b["channels"]["voice"]["ready"] and b["channels"]["face"]["ready"]
    # a normal day: with camera, or with the camera off, it is not low
    both = baseline.judge(b, 0.0, voice=-0.33, face=0.40)
    voice_only = baseline.judge(b, -0.33, voice=-0.33, face=None)
    assert both["relative"] and abs(both["value"]) < 0.05 and abs(voice_only["value"]) < 0.05
    assert masking.classify(0.6, voice_only["value"], True, voice_only["low_threshold"]) == "ok"
    # the voice drops while the face is kept normal (masking): still flagged
    drop = baseline.judge(b, 0.0, voice=-0.75, face=0.40)
    assert masking.classify(0.6, drop["value"], True, drop["low_threshold"]) == "masked"


def test_learning_period_uses_fixed_line():
    b = baseline.compute(_sessions([-0.3, -0.3], [None, None]))
    assert b["mode"] == "learning" and not b["ready"]
    assert baseline.judge(b, -0.4, voice=-0.4)["low_threshold"] == config.LOW_NONVERBAL_THRESHOLD


def test_old_fused_data_still_gets_a_baseline():
    sessions = [{"started_at": f"2026-10-0{i + 1}T09:00:00+05:30", "nonverbal_valence": v}
                for i, v in enumerate([-0.3, -0.28, -0.35, -0.31, -0.29])]
    b = baseline.compute(sessions)
    assert b["mode"] == "fused" and b["normal"] == -0.30


# ---------------------------------------------------------------- trends
TODAY = date(2026, 10, 19)


def _day_session(days_ago, nonverbal, readings=1, safety_flag=0, verbal=0.6):
    started = datetime.combine(TODAY - timedelta(days=days_ago), dtime(9, 0)).astimezone()
    return {"started_at": started.isoformat(), "verbal_valence": verbal, "nonverbal_valence": nonverbal,
            "reassurance": 1, "safety_flag": safety_flag, "readings": readings}


def test_day_weighted_by_readings():
    series = trends.daily_series([_day_session(0, -0.8, readings=1), _day_session(0, -0.2, readings=5)], 3, TODAY)
    assert series[-1]["nonverbal_valence"] == pytest.approx(-0.3)
    assert series[-1]["readings"] == 6


def test_typed_only_safety_day_still_raises_urgent():
    typed = _day_session(0, None, readings=0, safety_flag=1)
    series = trends.daily_series([typed, _day_session(1, 0.2)], 7, TODAY)
    assert series[-1]["safety_flag"] is True
    assert trends.alert(series, TODAY, TODAY)["level"] == "urgent"


# ---------------------------------------------------------------- readings
def test_speech_seconds_ignores_silence():
    import numpy as np
    from app.analysis import audio
    sr = audio.SAMPLE_RATE
    tone = 0.2 * np.sin(np.linspace(0, 2 * np.pi * 220 * 1.2, int(1.2 * sr)))
    clip = np.concatenate([np.zeros(sr // 2), tone, np.zeros(int(1.8 * sr))]).astype("float32")
    assert 1.0 <= audio.speech_seconds(clip) <= 1.4


def test_short_answers_are_not_readings():
    from app.services.conversation import is_reading
    def turn(speech_s, transcript="Yes."):
        return {"input": "voice", "transcript": transcript,
                "analysis": {"nonverbal": {"available": True, "speech_s": speech_s}}}
    assert not is_reading(turn(0.3))
    assert is_reading(turn(2.1, "I'm fine, nothing to worry about."))
    old = {"input": "voice", "transcript": "Hmm.", "analysis": {"nonverbal": {"available": True}}}
    assert not is_reading(old)                     # older data: word count


def test_voice_decides_when_face_stays_normal(monkeypatch):
    monkeypatch.setattr(config, "BASELINE_COMBINE", "voice")
    b = baseline.compute(_sessions([-0.35, -0.30, -0.33, -0.36, -0.31], [0.40, 0.35, 0.45, 0.38, 0.42]))
    j = baseline.judge(b, 0.1, voice=-0.70, face=0.42)    # smiling through it
    assert j["value"] == pytest.approx(-0.37, abs=0.01)
    face_only = baseline.judge(b, 0.1, voice=None, face=0.10)
    assert face_only["value"] == pytest.approx(-0.30, abs=0.01)   # no voice reading: face is used
