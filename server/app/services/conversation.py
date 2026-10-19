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
_pool = ThreadPoolExecutor(max_workers=4)


class ConversationError(Exception):
    """A problem the client should show to the user (bad input, unknown conversation...)."""


def now_local() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def _context(exclude_session: str | None = None, sensitive_open: bool = False) -> tuple:
    """(profile, recall dict, recall text, now) used to personalise replies. Unless the person has
    brought up a sensitive topic in this conversation, remembered lines naming it are left out."""
    p = profile_mod.load()
    now = now_local()
    recall = memory.recall(p, now.date(), exclude_session)
    text = memory.describe(recall, now.date())
    if not sensitive_open:
        text = "\n".join(line for line in text.split("\n") if not profile_mod.mentions_sensitive(p, line))
    return p, recall, text, now


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
    if profile_mod.mentions_sensitive(p, hook):
        hook = None   # never open a conversation with a sensitive topic
    daily_question = not db.wellbeing_answered_on(now.date().isoformat())
    greeting = (llm.greeting(p, memory_text, hook, now) if daily_question
                else llm.casual_greeting(p, memory_text, hook, now))
    db.create_session(session_id, now_iso(), greeting, is_demo=is_demo, checkin=daily_question)
    return {"session_id": session_id, "greeting_text": greeting,
            "greeting_audio_url": tts.speech_url(greeting, profile_mod.voice(p)),
            "daily_question": daily_question, "max_turns": config.MAX_TURNS_PER_SESSION,
            "companion_name": profile_mod.companion_name(p)}


def channel_valence(turn: dict, channel: str) -> float | None:
    """Voice or face valence of one message (older turns: computed from the stored probabilities)."""
    nv = turn["analysis"]["nonverbal"]
    if f"{channel}_valence" in nv:
        return nv[f"{channel}_valence"]
    ch = (nv.get("channels") or {}).get(channel)
    return fusion.valence(ch["probs"]) if ch and ch.get("probs") else None


def is_reading(turn: dict) -> bool:
    """A spoken message with a voice/face reading that is long enough to trust: very short answers
    ("hmm", "yes") give chance-level voice readings (evaluation/voice_short.py)."""
    nv = turn["analysis"]["nonverbal"]
    if turn.get("input", "voice") != "voice" or not nv.get("available"):
        return False
    if nv.get("speech_s") is not None:
        return nv["speech_s"] >= config.MIN_READING_SECONDS
    return len(turn["transcript"].split()) >= config.MIN_READING_WORDS


def summarize(turns: list, base: dict | None = None) -> dict:
    """Conversation summary, classified with the same masking rule as a single message:
    - seemed = mean non-verbal valence over spoken messages that gave a reading (is_reading),
               also per channel (voice, face) for the personal baseline
    - said   = mean verbal valence over the answer(s) to the daily question if there was one,
               otherwise over all messages (what they say about how they are matters most)
    A typed-only conversation has no "seemed" (None) and is left out of the mood trend."""
    base = base or baseline.compute([])
    spoken = [t for t in turns if is_reading(t)]
    wellbeing = [t for t in turns if t.get("context") == "wellbeing"]
    verbal = mean(t["verbal_valence"] for t in (wellbeing or turns))
    nonverbal = mean(t["nonverbal_valence"] for t in spoken) if spoken else None
    per_channel = {}
    for c in baseline.CHANNELS:
        vals = [v for v in (channel_valence(t, c) for t in spoken) if v is not None]
        per_channel[c] = mean(vals) if vals else None
    reassurance = any(t["analysis"]["verbal"]["reassurance"] for t in (wellbeing or turns))
    j = baseline.judge(base, nonverbal if nonverbal is not None else 0.0, per_channel["voice"], per_channel["face"])
    result = masking.analyse(verbal, j["value"], ["x"] if reassurance else [], j["low_threshold"])
    return {"turn_count": len(turns), "verbal_valence": verbal, "nonverbal_valence": nonverbal,
            "voice_valence": per_channel["voice"], "face_valence": per_channel["face"], "readings": len(spoken),
            "masking_score": result["masking_score"], "status": result["status"],
            "reassurance": int(reassurance),
            "safety_flag": int(any(t["safety_flag"] for t in turns))}


def backfill_channels() -> int:
    """Fills voice/face values and reading counts for sessions saved before they existed."""
    n = 0
    for s in db.list_sessions():
        if s.get("voice_valence") is None and s.get("face_valence") is None and s["turn_count"]:
            turns = db.get_turns(s["id"])
            if turns and any(is_reading(t) for t in turns):
                summary = summarize(turns)
                db.update_session(s["id"], voice_valence=summary["voice_valence"],
                                  face_valence=summary["face_valence"], readings=summary["readings"])
                n += 1
    return n


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
    per_channel = {f"{c}_valence": (fusion.valence(ch["probs"]) if ch else None) for c, ch in channels.items()}
    return {**fused, **per_channel, "speech_s": round(audio.speech_seconds(waveform), 2), "channels": channels}


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


def verbal_reading(transcript: str) -> tuple[dict, list]:
    """(sentiment, reassurance phrases) for what was said. "I'm fine, but I miss him": if the part
    after the "but" is more negative, that part is what counts and it isn't treated as reassurance
    (they are opening up, not masking). The sentiment model reads "I miss him" as neutral (+0.04), so
    the clause counts as opening up if it reads clearly negative OR has an emotion word; mild
    minimising ("just a bit tired", -0.29) stays a reassurance."""
    sentiment = text.predict(transcript)
    phrases = masking.find_reassurance(transcript)
    tail = masking.after_contrast(transcript)
    if tail:
        tail_sentiment = text.predict(tail)
        if tail_sentiment["valence"] <= OPENING_UP_VALENCE or plan.EMOTION_WORDS.search(tail.replace("’", "'")):
            valence = min(tail_sentiment["valence"], sentiment["valence"], config.NEGATIVE_VERBAL_THRESHOLD)
            return {**tail_sentiment, "valence": valence, "contrast": tail,
                    "whole_valence": sentiment["valence"]}, []
    return sentiment, phrases


OPENING_UP_VALENCE = -0.4   # "I'm fine, but <this>": at or below = they are saying they're not fine


def _late_safety(future, session_id: str, turn_index: int) -> None:
    """The self-harm screen answered after the reply was sent: still raise the family alert (the next
    reply then follows the safety guidance, because the message is now flagged)."""
    try:
        flagged, _model = future.result()
    except Exception:  # noqa: BLE001
        return
    if flagged:
        logger.warning("safety concern flagged late for session %s message %d", session_id[:8], turn_index + 1)
        db.flag_turn_safety(session_id, turn_index)


def _respond(session: dict, turns: list, transcript: str, nonverbal: dict, input_kind: str,
             t0: float, t_models: float) -> dict:
    session_id = session["id"]
    t_stt = time.perf_counter()
    p = profile_mod.load()
    user_texts = [t["transcript"] for t in turns] + [transcript]
    sensitive_open = profile_mod.sensitive_opened(p, user_texts)
    # Self-harm screen: keywords now, the LLM screen in parallel with the reply (analysis/safety.py).
    keyword_flag = safety.keyword_flag(transcript)
    screen_future = None if keyword_flag else _pool.submit(
        safety.llm_flag, transcript, [t["transcript"] for t in turns[-3:]], profile_mod.safety_background(p))
    safety_earlier = any(t["safety_flag"] for t in turns)
    p, recall, memory_text, now = _context(exclude_session=session_id, sensitive_open=sensitive_open)
    base = current_baseline(exclude_session=session_id)
    sentiment, phrases = verbal_reading(transcript)
    # how they seem, against their own normal; a message too short to trust is read on words alone
    reading = is_reading({"input": input_kind, "analysis": {"nonverbal": nonverbal}, "transcript": transcript})
    j = (baseline.judge(base, nonverbal["valence"], nonverbal.get("voice_valence"), nonverbal.get("face_valence"))
         if reading else {"value": 0.0, "low_threshold": base["fixed_low_threshold"], "relative": False})
    result = masking.analyse(sentiment["valence"], j["value"], phrases, j["low_threshold"])
    wellbeing = bool(session["checkin"]) and len(turns) == 0   # answer to the daily question
    analysis = {
        "verbal": {**sentiment, "reassurance": phrases},
        "nonverbal": nonverbal,
        **result,
        "safety_flag": keyword_flag,
        "safety": {"keyword": keyword_flag, "llm": None, "model": None},
        "low_threshold": j["low_threshold"],
        "vs_normal": j["value"] if j["relative"] else None,
        "reading": reading,
        "baseline": base,
    }
    care = plan.support(turns, result["status"], sentiment["valence"], wellbeing, input_kind == "voice",
                        transcript)
    analysis["support"] = care["mode"]
    analysis["support_suggested"] = care["suggest"]
    replies = [session["greeting"]] + [t["reply_text"] for t in turns]
    hints = plan.hints(p, recall, replies, db.replies_on(now.date().isoformat()), care["suggest"], now)
    late_screen = None
    if keyword_flag:
        reply_text = llm.safety_reply(p, first=not safety_earlier)
    else:
        reply_text = llm.reply(p, memory_text, _history(session, turns), transcript, result["status"], care,
                               hints, False, now, safety_earlier=safety_earlier, sensitive_open=sensitive_open)
        try:
            llm_flag, model = screen_future.result(timeout=config.SAFETY_SCREEN_WAIT_S)
        except Exception as exc:  # noqa: BLE001 -- not back in time: reply now, flag later if needed
            logger.warning("safety screen gave no answer in time: %s", exc)
            llm_flag, model = None, None
            late_screen = screen_future
        analysis["safety"].update(llm=llm_flag, model=model)
        if llm_flag:
            analysis["safety_flag"] = True
            # first, LLM-only flag: ask directly; a repeat or a clear "yes" gets the helpline reply
            reply_text = llm.safety_reply(p, first=not safety_earlier, ask=not safety_earlier)
            hints = []
    if analysis["safety_flag"]:
        logger.warning("safety concern flagged (keyword=%s, llm=%s)", keyword_flag, analysis["safety"]["llm"])
    t_llm = time.perf_counter()
    reply_audio = tts.speech_url(reply_text, profile_mod.voice(p))  # streams while playing

    turn_index = len(turns)
    db.add_turn(session_id, turn_index, now_iso(), transcript, reply_text, analysis,
                context="wellbeing" if wellbeing else "chat", input_kind=input_kind)
    if late_screen is not None:
        late_screen.add_done_callback(lambda f, idx=turn_index: _late_safety(f, session_id, idx))
    all_turns = db.get_turns(session_id)
    db.update_session(session_id, **summarize(all_turns, base))
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
