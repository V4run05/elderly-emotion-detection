"""Conversations with the companion, independent of any device or web framework.

A conversation is open-ended: the person talks (or types) as long as they like and the
companion replies in context. Once a day, the first conversation opens with "how are you
feeling today?" (the daily check-in question); that answer is what the masking check relies
on most. Every spoken message is also analysed for how the person *seems* (voice + face).

Any client (the browser page today, a Raspberry Pi later) sends the same inputs: an audio
file of what the person said plus 0..n camera frames, or typed text.

Start:      end any stale open conversation -> profile + memory recall -> greeting
            (personal "how are you feeling?" if not yet asked today, else a casual hello) -> voice
Message:    audio --ffmpeg--> voice emotion --\\
            frames ----------> face emotion ---+--> fused non-verbal valence ---\\
            audio --Whisper--> transcript --> sentiment + reassurance --> verbal -+--> masking status
            status + optional hints + profile + memory + recent history --> LLM reply --> streamed voice
            every MEMORY_EVERY_N_TURNS messages and at the end: background memory step
"""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from statistics import mean

from app import config
from app.analysis import audio, baseline, fusion, masking, safety
from app.companion import memory, plan
from app.companion import profile as profile_mod
from app.dialogue import llm, stt, tts
from app.models import face, text, voice
from app.storage import db

logger = logging.getLogger("uvicorn.error")
_pool = ThreadPoolExecutor(max_workers=2)


class ConversationError(Exception):
    """A problem the client should show to the user (bad input, unknown conversation...)."""


def now_local() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def _context(exclude_session: str | None = None) -> tuple:
    """(profile, recall dict, recall text, now) used to personalise replies."""
    p = profile_mod.load()
    now = now_local()
    recall = memory.recall(p, now.date(), exclude_session)
    return p, recall, memory.describe(recall, now.date()), now


def current_baseline(exclude_session: str | None = None) -> dict:
    sessions = [s for s in db.list_sessions() if s["id"] != exclude_session]
    return baseline.compute(sessions)


def _close(session: dict) -> None:
    if not session["ended_at"]:
        db.update_session(session["id"], ended_at=now_iso())
        if session["turn_count"]:
            memory.extract_in_background(session["id"])


def start(is_demo: bool = False) -> dict:
    for stale in db.open_sessions():   # a conversation left open (tab closed, etc.)
        _close(stale)
    session_id = uuid.uuid4().hex
    p, recall, memory_text, now = _context()
    hook = plan.greeting_hook(recall, now.date())
    daily_question = not db.wellbeing_answered_on(now.date().isoformat())
    greeting = (llm.greeting(p, memory_text, hook, now) if daily_question
                else llm.casual_greeting(p, memory_text, hook, now))
    db.create_session(session_id, now_iso(), greeting, is_demo=is_demo, checkin=daily_question)
    return {"session_id": session_id, "greeting_text": greeting,
            "greeting_audio_url": tts.speech_url(greeting, profile_mod.voice(p)),
            "daily_question": daily_question, "max_turns": config.MAX_TURNS_PER_SESSION,
            "companion_name": profile_mod.companion_name(p)}


def summarize(turns: list, low_threshold: float | None = None) -> dict:
    """Conversation summary, classified with the same masking rule as a single message:
    - seemed = mean non-verbal valence over SPOKEN messages that had a voice/face reading
    - said   = mean verbal valence over the answer(s) to the daily question if there was one,
               otherwise over all messages (what they say about how they are matters most)
    A typed-only conversation has no "seemed" (None) and is left out of the mood trend."""
    spoken = [t for t in turns if t.get("input", "voice") == "voice"
              and t["analysis"]["nonverbal"].get("available")]
    wellbeing = [t for t in turns if t.get("context") == "wellbeing"]
    verbal = mean(t["verbal_valence"] for t in (wellbeing or turns))
    nonverbal = mean(t["nonverbal_valence"] for t in spoken) if spoken else None
    reassurance = any(t["analysis"]["verbal"]["reassurance"] for t in (wellbeing or turns))
    result = masking.analyse(verbal, nonverbal if nonverbal is not None else 0.0,
                             ["x"] if reassurance else [], low_threshold)
    return {"turn_count": len(turns), "verbal_valence": verbal, "nonverbal_valence": nonverbal,
            "masking_score": result["masking_score"], "status": result["status"],
            "reassurance": int(reassurance),
            "safety_flag": int(any(t["safety_flag"] for t in turns))}


def _history(session: dict, turns: list) -> list:
    history = [{"role": "assistant", "content": session["greeting"]}]
    for t in turns[-config.HISTORY_TURNS:]:
        history += [{"role": "user", "content": t["transcript"]},
                    {"role": "assistant", "content": t["reply_text"]}]
    return history


def _nonverbal(waveform, images: list) -> dict:
    channels = {"voice": None, "face": None}
    quality = audio.voice_quality(waveform)
    if quality > 0:
        v = voice.predict(waveform)
        if v:
            channels["voice"] = {**v, "quality": quality}
    if images:
        channels["face"] = face.predict_frames(images)
    fused = fusion.fuse(channels)
    return {**fused, "channels": channels}


def _open_session(session_id: str) -> tuple:
    session = db.get_session(session_id)
    if session is None:
        raise ConversationError("Unknown conversation.")
    if session["ended_at"]:
        raise ConversationError("This conversation has ended. Start a new one.")
    turns = db.get_turns(session_id)
    limit = config.MAX_TURNS_PER_SESSION
    if limit and len(turns) >= limit:
        raise ConversationError("This conversation has reached its message limit.")
    return session, turns


def process_turn(session_id: str, audio_path: str, images: list) -> dict:
    """A spoken message. audio_path: any format ffmpeg reads. images: PIL images."""
    t0 = time.perf_counter()
    session, turns = _open_session(session_id)
    try:
        waveform = audio.load_waveform(audio_path)
    except ValueError as exc:
        raise ConversationError(f"Couldn't read the recording ({exc}).") from exc

    # Transcription is a network call; run it while the local models work on the audio/frames.
    quiet = audio.voice_quality(waveform) < 0.35  # lets STT drop silence hallucinations
    transcript_future = _pool.submit(stt.transcribe, audio_path, quiet)
    nonverbal = _nonverbal(waveform, images)
    t_models = time.perf_counter()
    try:
        transcript = transcript_future.result()
    except Exception as exc:  # noqa: BLE001 -- network/key problems; surface them to the user
        raise ConversationError(f"Speech recognition failed: {exc}") from exc
    if not transcript:
        p = profile_mod.load()
        retry = "Sorry, I didn't catch that. Could you say it again?"
        return {"heard": False, "transcript": "", "reply_text": retry,
                "reply_audio_url": tts.speech_url(retry, profile_mod.voice(p)), "session_done": False}
    return _respond(session, turns, transcript, nonverbal, "voice", t0, t_models)


def process_text(session_id: str, message: str) -> dict:
    """A typed message: no voice/face reading, so it can't show masking, only what was said."""
    t0 = time.perf_counter()
    session, turns = _open_session(session_id)
    message = message.strip()[:2000]
    if not message:
        raise ConversationError("Empty message.")
    nonverbal = {**fusion.fuse({}), "channels": {"voice": None, "face": None}}
    return _respond(session, turns, message, nonverbal, "typed", t0, time.perf_counter())


def _respond(session: dict, turns: list, transcript: str, nonverbal: dict, input_kind: str,
             t0: float, t_models: float) -> dict:
    session_id = session["id"]
    t_stt = time.perf_counter()
    p, recall, memory_text, now = _context(exclude_session=session_id)
    base = current_baseline(exclude_session=session_id)
    sentiment = text.predict(transcript)
    phrases = masking.find_reassurance(transcript)
    result = masking.analyse(sentiment["valence"], nonverbal["valence"], phrases, base["low_threshold"])
    flagged = safety.is_safety_concern(transcript)
    wellbeing = bool(session["checkin"]) and len(turns) == 0   # answer to the daily question
    analysis = {
        "verbal": {**sentiment, "reassurance": phrases},
        "nonverbal": nonverbal,
        **result,
        "safety_flag": flagged,
        "low_threshold": base["low_threshold"],
        "baseline": base,
    }
    care = plan.support(turns, result["status"], sentiment["valence"], wellbeing, input_kind == "voice",
                        transcript)
    analysis["support"] = care["mode"]
    analysis["support_suggested"] = care["suggest"]
    replies = [session["greeting"]] + [t["reply_text"] for t in turns]
    hints = plan.hints(p, recall, replies, db.replies_on(now.date().isoformat()), care["suggest"], now)
    reply_text = llm.reply(p, memory_text, _history(session, turns), transcript, result["status"], care,
                           hints, flagged, now)
    t_llm = time.perf_counter()
    reply_audio = tts.speech_url(reply_text, profile_mod.voice(p))  # streams while playing

    turn_index = len(turns)
    db.add_turn(session_id, turn_index, now_iso(), transcript, reply_text, analysis,
                context="wellbeing" if wellbeing else "chat", input_kind=input_kind)
    all_turns = db.get_turns(session_id)
    db.update_session(session_id, **summarize(all_turns, base["low_threshold"]))
    if len(all_turns) % config.MEMORY_EVERY_N_TURNS == 0:
        memory.extract_in_background(session_id)
    limit = config.MAX_TURNS_PER_SESSION
    done = bool(limit) and len(all_turns) >= limit
    if done:
        _close(db.get_session(session_id))

    timings = {"models": t_models - t0, "stt_wait": t_stt - t_models, "llm": t_llm - t_stt,
               "total": time.perf_counter() - t0}
    logger.info("message %s (%s) status=%s timings=%s", turn_index + 1, input_kind, result["status"],
                {k: round(v, 2) for k, v in timings.items()})
    return {
        "heard": True,
        "turn_index": turn_index,
        "transcript": transcript,
        "input": input_kind,
        "context": "wellbeing" if wellbeing else "chat",
        "reply_text": reply_text,
        "reply_audio_url": reply_audio,
        "session_done": done,
        "analysis": analysis,
        "hints": hints,
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
    }


def end(session_id: str) -> dict:
    session = db.get_session(session_id)
    if session is None:
        raise ConversationError("Unknown conversation.")
    _close(session)
    p = profile_mod.load()
    bye = llm.farewell(p, now_local())
    return {"session": db.get_session(session_id), "farewell_text": bye,
            "farewell_audio_url": tts.speech_url(bye, profile_mod.voice(p))}
