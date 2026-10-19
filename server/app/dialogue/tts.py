"""Text-to-speech. Providers, tried in order (the configured one first, then fallbacks):

    edge    - Microsoft neural voices via the `edge-tts` package (free, no key, needs
              internet). Default voice en-IN-NeerjaNeural: natural Indian-English female.
              ~1.4 s per reply. Unofficial use of the Edge "Read aloud" service.
    orpheus - Groq `canopylabs/orpheus-v1-english` (expressive, uses the existing Groq key).
              Requires a one-time terms acceptance in the Groq console, max 200 characters
              per request (we split by sentence and join the WAVs).
    gtts    - Google Translate TTS via `gTTS`. Last resort: works, but sounds robotic.

If every provider fails, the API returns no audio URL and the web client speaks the reply
with the browser's built-in speechSynthesis.

Streaming (default with edge): speech_url() returns /api/speech/<id> immediately and the audio
is generated while the browser is already playing it. Synthesising a two-sentence reply takes
~3.5 s with edge-tts, so waiting for the whole file made every reply feel slow. The bytes are
cached for a while so the browser can re-request them. Word timings (edge-tts WordBoundary
events) are recorded as the audio is generated, so the page can show each word as it's spoken
(GET /api/speech/<id>/timing).
"""

import asyncio
import logging
import re
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor

from app import config

logger = logging.getLogger("uvicorn.error")
ORPHEUS_MAX_CHARS = 200


def _edge(text: str, path, voice: str | None = None) -> None:
    import edge_tts

    async def run():
        await edge_tts.Communicate(text, voice or config.TTS_EDGE_VOICE,
                                   rate=config.TTS_EDGE_RATE).save(str(path))

    asyncio.run(run())


def _chunks(text: str, limit: int) -> list:
    """Split into pieces <= limit characters, preferring sentence then word boundaries."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if len(sentence) > limit and current:
            pieces.append(current)  # keep order: flush before splitting a long sentence
            current = ""
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _orpheus(text: str, path, voice: str | None = None) -> None:
    from groq import Groq

    client = Groq(api_key=config.GROQ_API_KEY)

    def synth(piece: str) -> bytes:
        resp = client.audio.speech.create(model="canopylabs/orpheus-v1-english",
                                          voice=config.TTS_ORPHEUS_VOICE, input=piece,
                                          response_format="wav")
        return resp.read()

    pieces = _chunks(text, ORPHEUS_MAX_CHARS)
    with ThreadPoolExecutor(max_workers=4) as pool:
        wavs = list(pool.map(synth, pieces))
    # Join the WAV pieces (same format from the same voice) into one file.
    import io

    with wave.open(str(path), "wb") as out:
        for i, data in enumerate(wavs):
            with wave.open(io.BytesIO(data)) as part:
                if i == 0:
                    out.setparams(part.getparams())
                out.writeframes(part.readframes(part.getnframes()))


def _gtts(text: str, path, voice: str | None = None) -> None:
    from gtts import gTTS

    gTTS(text, lang="en", tld=config.TTS_ACCENT).save(str(path))


PROVIDERS = {"edge": (_edge, "mp3"), "orpheus": (_orpheus, "wav"), "gtts": (_gtts, "mp3")}


def synthesize(text: str, voice: str | None = None) -> str | None:
    """Writes an audio file into AUDIO_DIR and returns its file name, or None if all fail.
    voice: an edge-tts voice id (from the profile); ignored by the other providers."""
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    order = [config.TTS_PROVIDER] + [p for p in ("edge", "gtts") if p != config.TTS_PROVIDER]
    for name in order:
        fn, ext = PROVIDERS[name]
        path = config.AUDIO_DIR / f"{uuid.uuid4().hex}.{ext}"
        try:
            fn(text, path, voice if name == "edge" else None)
            return path.name
        except Exception as exc:  # noqa: BLE001 -- try the next provider
            logger.warning("TTS provider '%s' failed: %s", name, exc)
            path.unlink(missing_ok=True)
    return None


# ---------------------------------------------------------------- streaming
_STREAMS: dict = {}          # id -> {"text", "voice", "created", "data": bytes | None, "words": [s], "done"}
_STREAMS_LOCK = threading.Lock()
STREAM_TTL_S = 15 * 60


def _prune() -> None:
    cutoff = time.time() - STREAM_TTL_S
    for sid in [k for k, v in _STREAMS.items() if v["created"] < cutoff]:
        _STREAMS.pop(sid, None)


def speech_url(text: str, voice: str | None = None) -> str | None:
    """URL the client can play right away. Streams with edge-tts; other providers synthesise
    a file first (as before)."""
    if config.TTS_PROVIDER != "edge":
        name = synthesize(text, voice)
        return f"/api/audio/{name}" if name else None
    sid = uuid.uuid4().hex
    with _STREAMS_LOCK:
        _prune()
        _STREAMS[sid] = {"text": text, "voice": voice, "created": time.time(), "data": None,
                         "words": [], "done": False}
    return f"/api/speech/{sid}"


def stream_entry(sid: str) -> dict | None:
    with _STREAMS_LOCK:
        return _STREAMS.get(sid)


async def stream(sid: str):
    """Async generator of MP3 bytes for a registered speech id (edge-tts, gTTS fallback)."""
    entry = stream_entry(sid)
    if entry is None:
        return
    if entry["data"] is not None:   # already generated: replay from cache
        yield entry["data"]
        return
    chunks = []
    try:
        import edge_tts

        comm = edge_tts.Communicate(entry["text"], entry["voice"] or config.TTS_EDGE_VOICE,
                                    rate=config.TTS_EDGE_RATE, boundary="WordBoundary")
        words = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
                yield chunk["data"]
            elif chunk["type"] == "WordBoundary":
                words.append(round(chunk["offset"] / 1e7, 3))   # 100-ns units -> seconds
                entry["words"] = words
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming TTS failed (%s); %s", exc, "falling back to gTTS" if not chunks else "partial audio")
        if not chunks:
            import io

            from gtts import gTTS

            buf = io.BytesIO()
            await asyncio.to_thread(lambda: gTTS(entry["text"], lang="en", tld=config.TTS_ACCENT).write_to_fp(buf))
            chunks.append(buf.getvalue())
            yield chunks[-1]
    entry["data"] = b"".join(chunks)
    entry["done"] = True


def timing(sid: str) -> dict | None:
    """Start time (seconds into the audio) of each spoken word so far; done = all words known."""
    entry = stream_entry(sid)
    if entry is None:
        return None
    return {"words": list(entry["words"]), "done": entry["done"]}
