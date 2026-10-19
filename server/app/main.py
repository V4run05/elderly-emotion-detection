"""HTTP API + static web client. All endpoints are under /api; the web client in clients/web
is served at / (talk page), /setup.html (profile setup) and /dashboard.html (family view).

API contract (any device, browser or Raspberry Pi, talks to exactly these):
    GET  /api/health                    model warm-up status, whether setup is done
    POST /api/sessions                  start a conversation -> greeting text + audio
    POST /api/sessions/{id}/turns       a spoken message. multipart: audio (required), images (0..n)
    POST /api/sessions/{id}/messages    a typed message. JSON {"text": "..."}
    POST /api/sessions/{id}/end         end the conversation -> farewell text + audio
    GET  /api/sessions/{id}             session + its turns
    GET  /api/dashboard?days=14         alert, daily trend, baseline, reminders, memories, wellbeing
    GET  /api/audio/{name}              generated reply audio (file)
    GET  /api/speech/{id}               reply audio streamed while it is generated
    GET  /api/speech/{id}/timing        start time of each spoken word (to show text as it's spoken)
    GET/PUT /api/profile                the person's profile (setup page)
    POST /api/voices/preview            sample of a voice for the setup page
    GET/POST /api/reminders, DELETE /api/reminders/{id}, POST /api/reminders/{id}/done
    GET /api/memories, DELETE /api/memories/{id}
    POST /api/onboarding, POST /api/onboarding/{id}/answer (multipart audio), POST /api/onboarding/{id}/finish
Details: docs/ARCHITECTURE.md ("API").
"""

import logging
import os
import shutil
import tempfile
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from app import config
from app.analysis import baseline, masking, trends
from app.companion import onboarding
from app.companion import profile as profile_mod
from app.companion import reminders as reminders_mod
from app.dialogue import llm, tts
from app.models import registry
from app.services import conversation
from app.storage import db

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    conversation.backfill_channels()   # per-channel values for sessions saved before they existed
    registry.preload_in_background()
    yield


app = FastAPI(title="I'm Fine companion", lifespan=lifespan)


@app.exception_handler(conversation.ConversationError)
@app.exception_handler(onboarding.OnboardingError)
async def _user_error(_request, exc: Exception):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/health")
def health():
    p = profile_mod.load()
    return {**registry.status(), "groq_key_set": bool(config.GROQ_API_KEY),
            "ffmpeg_found": shutil.which("ffmpeg") is not None,
            "configured": p["configured"], "elder_name": profile_mod.address_as(p),
            "companion_name": profile_mod.companion_name(p), "llm": llm.status()}


# ---------------------------------------------------------------- check-in
@app.post("/api/sessions")
def create_session():
    return conversation.start()


@app.post("/api/sessions/{session_id}/turns")
def add_turn(session_id: str, audio: UploadFile = File(...),
             images: list[UploadFile] = File(default=[])):
    suffix = Path(audio.filename or "answer.webm").suffix or ".webm"
    fd, audio_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(audio.file, f)
    frames = []
    for img in images:
        try:
            frames.append(Image.open(BytesIO(img.file.read())).convert("RGB"))
        except Exception:  # noqa: BLE001 -- a bad frame just gets skipped
            logger.warning("skipping unreadable image %s", img.filename)
    try:
        return conversation.process_turn(session_id, audio_path, frames)
    finally:
        if config.KEEP_MEDIA:
            keep = config.DATA_DIR / "media" / session_id
            keep.mkdir(parents=True, exist_ok=True)
            shutil.copy(audio_path, keep / f"{datetime.now():%H%M%S}{suffix}")
        os.remove(audio_path)


class TypedMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/sessions/{session_id}/messages")
def add_message(session_id: str, body: TypedMessage):
    return conversation.process_text(session_id, body.text)


@app.post("/api/sessions/{session_id}/end")
def end_session(session_id: str):
    return conversation.end(session_id)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Unknown session")
    return {**session, "turns": db.get_turns(session_id)}


@app.get("/api/audio/{name}")
def get_audio(name: str):
    path = (config.AUDIO_DIR / name).resolve()
    if path.parent != config.AUDIO_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="audio/wav" if path.suffix == ".wav" else "audio/mpeg")


@app.get("/api/speech/{sid}")
async def get_speech(sid: str):
    if tts.stream_entry(sid) is None:
        raise HTTPException(404, "Not found")
    return StreamingResponse(tts.stream(sid), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store"})


@app.get("/api/speech/{sid}/timing")
def get_speech_timing(sid: str):
    t = tts.timing(sid)
    if t is None:
        raise HTTPException(404, "Not found")
    return t


# ---------------------------------------------------------------- dashboard
def _wellbeing(sessions: list, today: date, days: int = 7) -> dict:
    """Per signal, how many of the last `days` days it was mentioned (poor sleep, pain, ...)."""
    since = (today - timedelta(days=days - 1)).isoformat()
    by_day = defaultdict(dict)
    for s in sessions:
        if s["started_at"][:10] >= since and s.get("signals"):
            day = by_day[s["started_at"][:10]]
            for k, v in s["signals"].items():
                if v in ("poor", "yes", "no"):
                    day.setdefault(k, set()).add(v)
    flag = {"sleep": "poor", "appetite": "poor", "pain": "yes", "loneliness": "yes", "social_contact": "no"}
    counts = {k: sum(1 for d in by_day.values() if want in d.get(k, set())) for k, want in flag.items()}
    return {"days": days, "days_with_signals": len(by_day), "counts": counts}


@app.get("/api/dashboard")
def dashboard(days: int = Query(14, ge=1, le=90)):
    p = profile_mod.load()
    now = conversation.now_local()
    today = now.date()
    all_sessions = db.list_sessions()
    base = conversation.current_baseline()
    low = base["low_threshold"]
    since = (today - timedelta(days=days - 1)).isoformat()
    analysed = [s for s in all_sessions if s["status"] and s["started_at"][:10] >= since]
    series = trends.daily_series(analysed, days, today, base=base)
    last = max((trends.session_day(s) for s in analysed), default=None)
    recent = []
    for s in analysed[:10]:
        turns = db.get_turns(s["id"])
        if s["nonverbal_valence"] is not None:   # re-judged against today's baseline
            j = baseline.judge(base, s["nonverbal_valence"], s.get("voice_valence"), s.get("face_valence"))
            status = masking.analyse(s["verbal_valence"], j["value"], ["x"] if s["reassurance"] else [],
                                     j["low_threshold"])["status"]
        else:
            status = s["status"]
        recent.append({**s, "status": status, "turns": [{
            "transcript": t["transcript"], "reply_text": t["reply_text"], "status": t["status"],
            "context": t["context"], "input": t["input"],
            "verbal_valence": t["verbal_valence"], "nonverbal_valence": t["nonverbal_valence"],
            "reassurance": t["analysis"]["verbal"]["reassurance"],
            "voice": (t["analysis"]["nonverbal"]["channels"].get("voice") or {}).get("label"),
            "face": (t["analysis"]["nonverbal"]["channels"].get("face") or {}).get("label"),
        } for t in turns]})
    return {
        "elder_name": profile_mod.elder_name(p), "companion_name": profile_mod.companion_name(p),
        "configured": p["configured"], "today": today.isoformat(),
        "alert": trends.alert(series, today, last, profile_mod.elder_name(p), profile_mod.pronouns(p)),
        "series": series, "recent_sessions": recent,
        "has_demo_data": any(s["is_demo"] for s in all_sessions),
        "baseline": base,
        "thresholds": {"low_nonverbal": low, "says_ok": config.SAYS_OK_THRESHOLD},
        "llm": llm.status(),
        "reminders": reminders_mod.today(now),
        "memories": db.list_memories(limit=40),
        "wellbeing": _wellbeing(all_sessions, today),
    }


# ---------------------------------------------------------------- profile / setup
@app.get("/api/profile")
def get_profile():
    p = profile_mod.load()
    return {"profile": p, "voices": profile_mod.VOICES, "styles": profile_mod.STYLES}


@app.put("/api/profile")
def put_profile(data: dict = Body(...)):
    return {"profile": profile_mod.save(data)}


class VoicePreview(BaseModel):
    voice: str = Field(max_length=80)
    text: str = Field(default="", max_length=200)


@app.post("/api/voices/preview")
def voice_preview(body: VoicePreview):
    text = body.text or "Hello! I'm looking forward to our chats. How are you feeling today?"
    return {"audio_url": tts.speech_url(text, body.voice)}


# ---------------------------------------------------------------- reminders
class ReminderIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="task", pattern="^(medication|task|appointment|call|other)$")
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: str = Field(default="daily", max_length=40)
    notes: str = Field(default="", max_length=200)


@app.get("/api/reminders")
def list_reminders():
    return {"today": reminders_mod.today(conversation.now_local()), "all": db.list_reminders()}


@app.post("/api/reminders")
def create_reminder(body: ReminderIn):
    rid = db.add_reminder(body.title.strip(), body.kind, body.time, body.days, body.notes.strip(),
                          "family", conversation.now_iso())
    return {"id": rid}


@app.delete("/api/reminders/{reminder_id}")
def remove_reminder(reminder_id: int):
    db.delete_reminder(reminder_id)
    return {"ok": True}


@app.post("/api/reminders/{reminder_id}/done")
def mark_reminder_done(reminder_id: int):
    now = conversation.now_local()
    db.log_reminder(reminder_id, now.date().isoformat(), "done", now.isoformat(timespec="seconds"), "dashboard")
    return {"ok": True}


# ---------------------------------------------------------------- memories
@app.get("/api/memories")
def list_memories():
    return {"memories": db.list_memories()}


@app.delete("/api/memories/{memory_id}")
def remove_memory(memory_id: int):
    db.delete_memory(memory_id)
    return {"ok": True}


# ---------------------------------------------------------------- get to know you (onboarding)
@app.post("/api/onboarding")
def onboarding_start():
    return onboarding.start()


@app.post("/api/onboarding/{oid}/answer")
def onboarding_answer(oid: str, audio: UploadFile = File(...)):
    suffix = Path(audio.filename or "answer.webm").suffix or ".webm"
    fd, audio_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(audio.file, f)
    try:
        return onboarding.answer(oid, audio_path)
    finally:
        os.remove(audio_path)


@app.post("/api/onboarding/{oid}/finish")
def onboarding_finish(oid: str):
    return onboarding.finish(oid)


@app.get("/dashboard")
def dashboard_page():
    return RedirectResponse("/dashboard.html")


@app.get("/setup")
def setup_page():
    return RedirectResponse("/setup.html")


# Must be last: catches every path not matched above.
app.mount("/", StaticFiles(directory=config.WEB_CLIENT_DIR, html=True), name="web")
