import logging
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.voice_emotion.preprocess import load_waveform
from app.voice_emotion.model import predict as predict_voice
from app.face_emotion.model import predict as predict_face
from app.fusion.fuse import fuse_emotions
from app.dialogue.stt_client import transcribe
from app.dialogue.llm_client import generate_response
from app.tts.synthesize import synthesize
from app.storage.mood_log import log_checkin
from app.storage.conversation import add_turn, get_recent_turns, reset_conversation

logger = logging.getLogger("uvicorn.error")

app = FastAPI()


@app.post("/checkin")
async def checkin(file: UploadFile = File(...), image: Optional[UploadFile] = File(None)):
    try:
        suffix = Path(file.filename or "clip.m4a").suffix or ".m4a"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
            tmp_in.write(await file.read())
            input_path = tmp_in.name

        waveform = load_waveform(input_path)
        voice_result = predict_voice(waveform)
        user_text = transcribe(input_path)

        face_result = None
        if image is not None:
            img_suffix = Path(image.filename or "face.jpg").suffix or ".jpg"
            with tempfile.NamedTemporaryFile(suffix=img_suffix, delete=False) as tmp_img:
                tmp_img.write(await image.read())
                image_path = tmp_img.name
            try:
                face_result = predict_face(image_path)
            except Exception as exc:
                # Face is an optional signal -- a decode failure or no-face-detected shouldn't
                # break the whole check-in, just fall back to voice-only.
                logger.warning("face_emotion prediction failed, falling back to voice-only: %s", exc)

        result = fuse_emotions(voice_result, face_result)

        timestamp = datetime.now(timezone.utc).isoformat()
        log_checkin(result["label"], result["confidence"], timestamp)

        conversation_history = get_recent_turns(10)
        response_text = generate_response(user_text, result["label"], conversation_history)

        add_turn("user", user_text, timestamp)
        add_turn("assistant", response_text, datetime.now(timezone.utc).isoformat())

        output_path = str(Path(tempfile.gettempdir()) / f"response_{Path(input_path).stem}.mp3")
        synthesize(response_text, output_path)

        headers = {
            # Header values must be Latin-1/ASCII-safe, so free text is percent-encoded;
            # the client URL-decodes these before displaying them.
            "X-User-Text": quote(user_text),
            "X-Emotion-Label": quote(result["label"]),
            "X-Emotion-Confidence": f"{result['confidence']:.4f}",
            "X-Response-Text": quote(response_text),
            "X-Voice-Label": quote(voice_result["label"]),
            "X-Voice-Confidence": f"{voice_result['confidence']:.4f}",
        }
        if face_result is not None:
            headers["X-Face-Label"] = quote(face_result["label"])
            headers["X-Face-Confidence"] = f"{face_result['confidence']:.4f}"

        return FileResponse(
            output_path,
            media_type="audio/mpeg",
            filename="response.mp3",
            headers=headers,
        )
    except Exception as exc:
        logger.error("checkin failed: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/reset")
async def reset():
    reset_conversation()
    return {"status": "ok"}
