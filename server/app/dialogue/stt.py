"""Speech-to-text via Groq's hosted Whisper (whisper-large-v3 by default, see config).

- Sends the ORIGINAL upload (Whisper decodes webm/m4a/wav itself), not the ffmpeg copy.
- temperature 0 and language "en" (both recommended by Groq for accuracy).
- No `prompt`: tested on noisy Indian-English clips (2026-10-19), a descriptive context prompt
  made Whisper invent narrative text ("Lakshmi replied, ...") and raised word errors from
  11.4% to 18.6%; passing only the last question gave no improvement. See docs/CHANGELOG.md.
"""

import os
import re

from app import config

# Whisper "hears" these on silence/noise (well-known hallucinations). Only dropped when the
# clip itself was quiet, so a real spoken "Thank you" is kept.
HALLUCINATIONS = {"you", "thank you", "thanks for watching", "thank you for watching",
                  "bye", "so", "uh", "um", "hmm", ""}


def clean(text: str, quiet: bool) -> str:
    """Returns the transcript, or "" if it's a known silence hallucination on a quiet clip."""
    text = text.strip()
    key = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if key == "" or (quiet and key in HALLUCINATIONS):
        return ""
    return text


def transcribe(audio_path: str, quiet: bool = False) -> str:
    from groq import Groq

    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in server/.env")
    client = Groq(api_key=config.GROQ_API_KEY)
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=config.STT_MODEL,
            file=(os.path.basename(audio_path), f.read()),
            language="en",
            temperature=0.0,
        )
    return clean(result.text, quiet)
