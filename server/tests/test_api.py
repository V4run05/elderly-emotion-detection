"""End-to-end API flow with every model and cloud call replaced by a stub, so it runs in a
second without a Groq key, network, or model downloads. Real-model checks live in
scripts/smoke_test.py."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = {
    "elder": {"full_name": "Lakshmi Iyer", "preferred_name": "Lakshmi", "pronouns": "she"},
    "people": [{"name": "Priya", "relation": "granddaughter", "notes": "studies in Bangalore", "birthday": ""}],
    "interests": "gardening, old Hindi songs",
    "companion": {"name": "Asha", "voice": "en-IN-NeerjaNeural", "style": "warm", "address_as": "Lakshmi Amma"},
    "reminders": [{"title": "BP tablet", "kind": "medication", "time": "09:00", "days": "daily"}],
}


@pytest.fixture
def stubs(tmp_path, monkeypatch):
    from app import config
    from app.companion import memory
    from app.models import face, registry, text, voice
    from app.services import conversation as checkin

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(registry, "preload_in_background", lambda: None)

    sad = {"label": "Sadness", "confidence": 0.8,
           "probs": {"Anger": 0.0, "Happiness": 0.05, "Neutral": 0.15, "Sadness": 0.8}}
    monkeypatch.setattr(voice, "predict", lambda *a, **k: dict(sad))
    monkeypatch.setattr(face, "predict_frames",
                        lambda imgs: {**sad, "quality": 1.0, "frames_used": len(imgs),
                                      "frames_total": len(imgs)})
    monkeypatch.setattr(text, "predict", lambda t: {"valence": 0.7, "probs": {
        "positive": 0.75, "neutral": 0.2, "negative": 0.05}})
    monkeypatch.setattr(checkin.stt, "transcribe", lambda *a, **k: "I'm fine, nothing to worry about.")
    calls = []

    def fake_complete(messages, *args, **kwargs):
        calls.append(messages)
        return "That's good to hear. How did you sleep?"
    monkeypatch.setattr(checkin.llm, "complete", fake_complete)
    monkeypatch.setattr(checkin.tts, "synthesize", lambda text, voice=None: None)
    monkeypatch.setattr(checkin.tts, "speech_url", lambda text, voice=None: None)
    extracted = []
    monkeypatch.setattr(memory, "extract_in_background", lambda sid: extracted.append(sid))
    return {"llm_calls": calls, "extracted": extracted}


@pytest.fixture
def client(stubs):
    from app.main import app
    with TestClient(app) as c:
        yield c


def post_turn(client, session_id, with_image=True):
    files = [("audio", ("answer.wav", (FIXTURES / "test_clip.wav").read_bytes(), "audio/wav"))]
    if with_image:
        files.append(("images", ("f.jpg", (FIXTURES / "face_astronaut.jpg").read_bytes(), "image/jpeg")))
    return client.post(f"/api/sessions/{session_id}/turns", files=files)


def test_open_conversation_detects_masking(client, stubs):
    s = client.post("/api/sessions").json()
    assert s["greeting_text"] and s["daily_question"] is True and s["max_turns"] == 0

    for i in range(6):   # open-ended: no limit
        r = post_turn(client, s["session_id"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["turn_index"] == i and body["session_done"] is False
        assert body["analysis"]["status"] == "masked"
        assert body["context"] == ("wellbeing" if i == 0 else "chat")
    assert stubs["extracted"] == [s["session_id"]]   # memory step after 4 messages

    end = client.post(f"/api/sessions/{s['session_id']}/end").json()
    assert end["farewell_text"] and end["session"]["ended_at"]
    assert stubs["extracted"] == [s["session_id"]] * 2   # and again at the end
    assert post_turn(client, s["session_id"]).status_code == 400   # ended

    dash = client.get("/api/dashboard").json()
    assert dash["series"][-1]["status"] == "masked"
    assert dash["recent_sessions"][0]["turns"][0]["voice"] == "Sadness"
    assert dash["alert"]["level"] in ("ok", "watch")  # one masked day alone is not an alert
    assert dash["baseline"]["ready"] is False         # 1 of 5 calibration conversations


def test_daily_question_only_once_a_day_and_typed_messages(client, stubs):
    first = client.post("/api/sessions").json()
    post_turn(client, first["session_id"])
    second = client.post("/api/sessions").json()      # also closes the first one
    assert second["daily_question"] is False
    from app.storage import db
    assert db.get_session(first["session_id"])["ended_at"]

    r = client.post(f"/api/sessions/{second['session_id']}/messages", json={"text": "Tell me about old films"})
    body = r.json()
    assert r.status_code == 200 and body["input"] == "typed" and body["context"] == "chat"
    assert body["analysis"]["nonverbal"]["available"] is False
    s = client.get(f"/api/sessions/{second['session_id']}").json()
    assert s["nonverbal_valence"] is None              # typed-only: no "seemed", not in the trend
    assert client.post(f"/api/sessions/{second['session_id']}/messages", json={"text": ""}).status_code == 422


def test_profile_personalises_prompt_and_reminders(client, stubs):
    assert client.get("/api/health").json()["configured"] is False
    r = client.put("/api/profile", json=PROFILE)
    assert r.status_code == 200
    health = client.get("/api/health").json()
    assert health["configured"] and health["elder_name"] == "Lakshmi Amma"

    reminders = client.get("/api/reminders").json()
    assert [x["title"] for x in reminders["today"]] == ["BP tablet"]

    s = client.post("/api/sessions").json()
    post_turn(client, s["session_id"])
    system = stubs["llm_calls"][-1][0]["content"]
    assert "Priya (granddaughter)" in system and "Lakshmi Amma" in system and "gardening" in system

    # editing the profile replaces setup reminders but keeps family-added ones
    client.post("/api/reminders", json={"title": "Call Priya", "kind": "call", "time": "18:00"})
    client.put("/api/profile", json={**PROFILE, "reminders": []})
    titles = [x["title"] for x in client.get("/api/reminders").json()["all"]]
    assert titles == ["Call Priya"]


def test_companion_name_can_be_changed(client, stubs):
    client.put("/api/profile", json={**PROFILE, "companion": {**PROFILE["companion"], "name": "Meera"}})
    assert client.get("/api/health").json()["companion_name"] == "Meera"
    s = client.post("/api/sessions").json()
    assert s["companion_name"] == "Meera"
    post_turn(client, s["session_id"])
    assert "You are Meera" in stubs["llm_calls"][-1][0]["content"]


def test_reminder_done_and_memory_endpoints(client):
    rid = client.post("/api/reminders", json={"title": "Walk", "time": "07:00"}).json()["id"]
    client.post(f"/api/reminders/{rid}/done")
    today = client.get("/api/reminders").json()["today"]
    assert today[0]["status"] == "done" and today[0]["confirmed_by"] == "dashboard"

    from app.storage import db
    mid = db.add_memory("2026-10-19T10:00:00+05:30", "event", "Priya's exam is on Friday", "Priya",
                        "2026-10-23", None)
    assert client.get("/api/memories").json()["memories"][0]["text"] == "Priya's exam is on Friday"
    client.delete(f"/api/memories/{mid}")
    assert client.get("/api/memories").json()["memories"] == []


def test_bad_reminder_rejected(client):
    assert client.post("/api/reminders", json={"title": "x", "time": "25:00"}).status_code == 422


def test_unknown_session_is_400(client):
    assert post_turn(client, "nope").status_code == 400


def test_health_and_static_pages(client):
    assert "models" in client.get("/api/health").json()
    assert "Talk · I'm Fine" in client.get("/").text
    assert "Dashboard · I'm Fine" in client.get("/dashboard.html").text
    assert "Setup · I'm Fine" in client.get("/setup.html").text


def test_get_to_know_you_fills_profile_without_counting_as_checkin(client, monkeypatch):
    from app.companion import onboarding
    patches = {
        "What would you like me to call you?": {"preferred_name": "Lakshmi"},
        "Who are the people who matter most to you? Tell me their names and how you know them.":
            {"people": [{"name": "Priya", "relation": "granddaughter", "notes": "in Bangalore"},
                        {"name": "Kamala", "relation": "neighbour", "notes": ""}]},
        "Are there any medicines or daily tasks you'd like me to remind you about? Tell me the times too.":
            {"reminders": [{"title": "BP tablet", "kind": "medication", "time": "09:00", "days": "daily"}]},
    }
    monkeypatch.setattr(onboarding, "_extract", lambda q, t: patches.get(q, {"skipped": True}))
    s = client.post("/api/onboarding").json()
    assert s["total"] == len(onboarding.TOPICS) and "call you" in s["text"]
    files = [("audio", ("a.wav", (FIXTURES / "test_clip.wav").read_bytes(), "audio/wav"))]
    done, learned = False, []
    for _ in range(s["total"]):
        r = client.post(f"/api/onboarding/{s['onboarding_id']}/answer", files=files).json()
        learned += r["learned"]
        done = r["done"]
    assert done and "Name: Lakshmi" in learned and "Reminder: BP tablet at 09:00" in learned
    p = client.get("/api/profile").json()["profile"]
    assert p["configured"] and p["elder"]["preferred_name"] == "Lakshmi"
    assert [x["name"] for x in p["people"]] == ["Priya", "Kamala"]
    assert [r["title"] for r in client.get("/api/reminders").json()["all"]] == ["BP tablet"]
    assert client.get("/api/dashboard").json()["recent_sessions"] == []   # not a check-in
    assert client.post(f"/api/onboarding/{s['onboarding_id']}/answer", files=files).status_code == 400


def test_speech_stream_endpoint_serves_cached_audio(client):
    from app.dialogue import tts
    assert client.get("/api/speech/nope").status_code == 404
    sid = "abc123"
    tts._STREAMS[sid] = {"text": "hi", "voice": None, "created": 9e18, "data": b"ID3fake-mp3"}
    r = client.get(f"/api/speech/{sid}")
    assert r.status_code == 200 and r.content == b"ID3fake-mp3"
    assert r.headers["content-type"] == "audio/mpeg"
    tts._STREAMS[sid].update({"words": [0.1, 0.5, 0.9], "done": True})
    assert client.get(f"/api/speech/{sid}/timing").json() == {"words": [0.1, 0.5, 0.9], "done": True}
    assert client.get("/api/speech/nope/timing").status_code == 404
