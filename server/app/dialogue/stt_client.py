"""Speech-to-text via Groq's hosted Whisper endpoint, so the LLM can respond to what the
person actually said, not just the emotion label detected from their voice."""

import os


def transcribe(audio_path: str) -> str:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    with open(audio_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=(os.path.basename(audio_path), f.read()),
        )
    return transcription.text.strip()
