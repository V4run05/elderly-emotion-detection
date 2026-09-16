import logging
import os
import tempfile
import traceback
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.voice_emotion.preprocess import load_waveform
from app.voice_emotion.model import predict as predict_voice
from app.face_emotion.model import predict as predict_face
from app.physio_emotion.model import predict as predict_physio
from app.fusion.fuse import fuse_emotions
from app.dialogue.stt_client import transcribe
from app.dialogue.llm_client import generate_response
from app.tts.synthesize import synthesize
from app.storage.mood_log import log_checkin, log_trigger_event, get_recent, get_recent_triggers
from app.storage.conversation import add_turn, get_recent_turns, reset_conversation

logger = logging.getLogger("uvicorn.error")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory tracker for the POC
trigger_state = {
    "active": False,
    "event_type": None,
    "prompted_at": None,
}

# Cache for asynchronous modalities
latest_modalities = {
    "voice": None,
    "face": None,
    "physio": None
}

def evaluate_triggers(physio_data: dict, timestamp: str):
    """Evaluate physiological triggers and update state machine."""
    hr = physio_data.get("hr", 0)
    spo2 = physio_data.get("spo2", 100)
    accel = physio_data.get("accel_magnitude", 0)
    
    event_type = None
    if hr > 100:
        event_type = "HR_SPIKE"
    elif spo2 < 92:
        event_type = "SPO2_DROP"
    elif accel > 3.0:
        event_type = "FALL_DETECTED"
        
    if event_type:
        if not trigger_state["active"]:
            # Stage 1: Prompt
            trigger_state["active"] = True
            trigger_state["event_type"] = event_type
            trigger_state["prompted_at"] = timestamp
            trigger_state["escalated"] = False
            log_trigger_event(event_type, "PROMPT_USER", timestamp)
            add_turn("assistant", f"I noticed a {event_type} alert. Are you feeling okay?", timestamp)
            return {"action": "waiting_for_user", "event": event_type}
        else:
            # Check for Stage 2: Escalate (e.g. > 30s without response)
            prompted_time = datetime.fromisoformat(trigger_state["prompted_at"])
            now = datetime.fromisoformat(timestamp)
            if (now - prompted_time).total_seconds() > 30 and not trigger_state.get("escalated"):
                log_trigger_event(trigger_state["event_type"], "ESCALATED", timestamp)
                trigger_state["escalated"] = True
                add_turn("assistant", f"You haven't responded, and the {trigger_state['event_type']} alert is still active. I am contacting your caregiver.", timestamp)
            
            if trigger_state.get("escalated"):
                return {"action": "escalated", "event": trigger_state["event_type"]}
            return {"action": "waiting_for_user", "event": trigger_state["event_type"]}
    else:
        # If no trigger event but we were active, we could resolve it automatically
        if trigger_state["active"]:
            trigger_state["active"] = False
            trigger_state["escalated"] = False
            trigger_state["event_type"] = None
            add_turn("assistant", "Your heart rate has returned to normal. Glad you're okay.", timestamp)
        
    return None

@app.post("/checkin")
async def checkin(
    file: UploadFile = File(None), 
    image: Optional[UploadFile] = File(None),
    physio_json: Optional[str] = Form(None)
):
    try:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        global latest_modalities
        
        user_text = ""
        # 1. Voice
        if file is not None:
            try:
                suffix = Path(file.filename or "clip.m4a").suffix or ".m4a"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
                    tmp_in.write(await file.read())
                    input_path = tmp_in.name
                waveform = load_waveform(input_path)
                voice_result = predict_voice(waveform)
                latest_modalities["voice"] = {"data": voice_result, "time": now}
            except Exception as exc:
                logger.warning("voice_emotion prediction failed: %s", exc)
                
            try:
                user_text = transcribe(input_path)
            except Exception as exc:
                logger.warning("stt failed: %s", exc)
                
        # 2. Face
        if image is not None:
            try:
                img_suffix = Path(image.filename or "face.jpg").suffix or ".jpg"
                with tempfile.NamedTemporaryFile(suffix=img_suffix, delete=False) as tmp_img:
                    tmp_img.write(await image.read())
                    image_path = tmp_img.name
                face_result = predict_face(image_path)
                latest_modalities["face"] = {"data": face_result, "time": now}
            except Exception as exc:
                logger.warning("face_emotion prediction failed: %s", exc)

        # 3. Physio
        actionable_state = None
        if physio_json:
            try:
                physio_data = json.loads(physio_json)
                physio_result = predict_physio(physio_data)
                latest_modalities["physio"] = {"data": physio_result, "time": now}
                actionable_state = evaluate_triggers(physio_data, timestamp)
            except Exception as exc:
                logger.warning("physio_emotion prediction failed: %s", exc)

        # 4. Fusion across whatever we currently have in cache that isn't stale (>5 mins)
        active_modalities = {}
        for mod, entry in latest_modalities.items():
            if entry is not None:
                age = (now - entry["time"]).total_seconds()
                if age < 300:
                    active_modalities[mod] = entry["data"]
                else:
                    latest_modalities[mod] = None # Expire stale modality

        result = fuse_emotions(active_modalities)

        log_checkin(result["label"], result["confidence"], result["quality_scores"], timestamp)

        # Generate LLM response ONLY if we successfully got text and aren't crashing
        output_path = None
        response_text = ""
        if user_text:
            try:
                conversation_history = get_recent_turns(10)
                response_text = generate_response(user_text, result["label"], conversation_history)
                add_turn("user", user_text, timestamp)
                add_turn("assistant", response_text, timestamp)

                output_path = str(Path(tempfile.gettempdir()) / f"response_{timestamp.replace(':', '')}.mp3")
                synthesize(response_text, output_path)
            except Exception as exc:
                logger.warning("llm/tts failed: %s", exc)
                output_path = None

        if output_path and os.path.exists(output_path):
            headers = {
                "X-User-Text": quote(user_text),
                "X-Emotion-Label": quote(result["label"]),
                "X-Emotion-Confidence": f"{result['confidence']:.4f}",
                "X-Response-Text": quote(response_text),
            }
            if actionable_state:
                headers["X-Action"] = quote(actionable_state["action"])
                headers["X-Action-Event"] = quote(actionable_state["event"])

            return FileResponse(
                output_path,
                media_type="audio/mpeg",
                filename="response.mp3",
                headers=headers,
            )
        else:
            # If it's a silent checkin or TTS failed, just return JSON
            resp = {
                "emotion_label": result["label"],
                "confidence": result["confidence"],
                "quality_scores": result["quality_scores"]
            }
            if actionable_state:
                resp["action"] = actionable_state["action"]
                resp["event"] = actionable_state["event"]
            return JSONResponse(content=resp)
            
    except Exception as exc:
        logger.error("checkin failed: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/reset")
async def reset():
    reset_conversation()
    global trigger_state
    trigger_state = {"active": False, "event_type": None, "prompted_at": None}
    return {"status": "ok"}

@app.post('/chat')
async def chat_message(text: str = Form(...)):
    now = datetime.now(timezone.utc).isoformat()
    add_turn("user", text, now)

    # Simple simulated response if no GROQ_API_KEY
    if "GROQ_API_KEY" not in os.environ:
        reply = "I understand. I am here for you. (Note: Groq API key is missing, so I cannot generate a full AI response)."
    else:
        # Get latest fused emotion if available, else Neutral
        emotion = "Neutral"
        for entry in latest_modalities.values():
            if entry is not None:
                emotion = entry["data"]["label"]
                break

        history = get_recent_turns(10)
        reply = generate_response(text, emotion, history[:-1])

    add_turn("assistant", reply, datetime.now(timezone.utc).isoformat())
    return {"status": "ok", "reply": reply}

@app.get('/state')
async def get_state():
    now = datetime.now(timezone.utc)
    mod_summary = {}
    for mod, entry in latest_modalities.items():
        if entry is not None:
            if (now - entry["time"]).total_seconds() < 300:
                mod_summary[mod] = {
                    "label": entry["data"]["label"],
                    "confidence": entry["data"]["confidence"],
                    "quality": entry["data"]["quality_score"]
                }
                
    return {
        'recent_checkins': get_recent(10),
        'recent_triggers': get_recent_triggers(10),
        'trigger_state': trigger_state,
        'active_modalities': mod_summary,
        'conversation': get_recent_turns(10)
    }
