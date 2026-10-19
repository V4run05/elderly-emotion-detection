"""Time each step of one spoken message on this machine (run with nothing else heavy running).

Local models: voice (one 3 s clip), face (one frame), text sentiment. Network: Groq Whisper STT,
the companion LLM (whichever --llm model), edge-tts time to first audio bytes.

    python evaluation/latency_bench.py [--n 10] [--llm openai/gpt-oss-20b]
"""

import argparse
import asyncio
import json
import statistics
import time

from PIL import Image

from common import DATASETS, RESULTS, groq_chat

from app import config
from app.analysis import audio
from app.dialogue import stt
from app.models import face, registry, text, voice

FIXTURES = DATASETS.parent.parent / "tests" / "fixtures"


def timed(fn, n):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return {"median_s": round(statistics.median(out), 3), "max_s": round(max(out), 3), "n": n}


async def edge_first_byte(textline):
    import edge_tts
    t = time.perf_counter()
    async for chunk in edge_tts.Communicate(textline, config.TTS_EDGE_VOICE).stream():
        if chunk["type"] == "audio":
            return time.perf_counter() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--llm", default=config.LLM_FAST_MODEL)
    args = ap.parse_args()
    for m in ("voice", "face", "text"):
        registry.ensure_loaded(m)
    clip = next((DATASETS / "crema" / "data" / "AudioWAV").glob("1001_DFA_SAD_XX.wav"))
    wave = audio.load_waveform(str(clip))
    img = Image.open(FIXTURES / "face_astronaut.jpg").convert("RGB")
    res = {
        "voice_model_3s_clip": timed(lambda: voice.predict(wave), args.n),
        "face_model_frame": timed(lambda: face.predict_frame(img), args.n),
        "text_model": timed(lambda: text.predict("I'm fine, nothing to worry about."), args.n),
        "stt_groq_whisper": timed(lambda: stt.transcribe(str(FIXTURES / "test_clip.m4a"), False), min(args.n, 5)),
    }
    msgs = [{"role": "system", "content": "You are a warm companion. Reply in two short sentences."},
            {"role": "user", "content": "I watered my roses this morning and they look lovely."}]
    try:
        res[f"llm_{args.llm.split('/')[-1]}"] = timed(lambda: groq_chat(args.llm, msgs, max_tokens=600), min(args.n, 5))
    except Exception as exc:  # noqa: BLE001
        res["llm_error"] = str(exc)[:200]
    tts = [asyncio.run(edge_first_byte("That sounds lovely, Lakshmi Amma. Which colour bloomed first?"))
           for _ in range(min(args.n, 5))]
    res["tts_edge_first_audio"] = {"median_s": round(statistics.median(tts), 3), "max_s": round(max(tts), 3)}
    (RESULTS / "latency.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    for k, v in res.items():
        print(f"  {k:<26} {v}")


if __name__ == "__main__":
    main()
