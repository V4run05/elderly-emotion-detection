import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse

from app.voice_emotion.preprocess import load_waveform
from app.voice_emotion.model import predict
from app.dialogue.llm_client import generate_response
from app.tts.synthesize import synthesize
from app.storage.mood_log import log_checkin, get_recent

app = FastAPI()


@app.post("/checkin")
async def checkin(file: UploadFile):
    suffix = Path(file.filename or "clip.m4a").suffix or ".m4a"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        tmp_in.write(await file.read())
        input_path = tmp_in.name

    waveform = load_waveform(input_path)
    result = predict(waveform)

    timestamp = datetime.now(timezone.utc).isoformat()
    log_checkin(result["label"], result["confidence"], timestamp)

    mood_history = get_recent(5)
    response_text = generate_response(result["label"], mood_history)

    output_path = str(Path(tempfile.gettempdir()) / f"response_{Path(input_path).stem}.mp3")
    synthesize(response_text, output_path)

    return FileResponse(output_path, media_type="audio/mpeg", filename="response.mp3")
