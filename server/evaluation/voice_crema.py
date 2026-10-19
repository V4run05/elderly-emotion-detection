"""Run the real voice-emotion model on CREMA-D (91 actors aged 20-74, acted emotional speech).

Writes one row per clip to results/raw/crema_voice.csv (resumable). Only the 4 emotions that
map onto our classes are used: ANG, HAP, NEU, SAD. Sentences are neutral in content
("It's eleven o'clock"), so only the voice carries the emotion.

    python evaluation/voice_crema.py [--limit N]
"""

import argparse
import time

from common import DATASETS, RAW, append_csv, read_csv

from app.analysis import audio, fusion
from app.models import registry, voice

EMOTIONS = {"ANG": "Anger", "HAP": "Happiness", "NEU": "Neutral", "SAD": "Sadness"}
OUT = RAW / "crema_voice.csv"
FIELDS = ["file", "actor", "age", "sex", "sentence", "emotion", "level", "pred", "confidence",
          "p_anger", "p_happiness", "p_neutral", "p_sadness", "valence", "quality"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    demo = {r["ActorID"]: r for r in read_csv(DATASETS / "crema" / "VideoDemographics.csv")}
    wavs = sorted((DATASETS / "crema" / "data" / "AudioWAV").glob("*.wav"))
    wavs = [w for w in wavs if w.stem.split("_")[2] in EMOTIONS]
    done = {r["file"] for r in read_csv(OUT)} if OUT.exists() else set()
    todo = [w for w in wavs if w.name not in done][: args.limit or None]
    print(f"{len(wavs)} clips in scope, {len(done)} done, {len(todo)} to run", flush=True)

    registry.ensure_loaded("voice")
    t0 = time.time()
    for i, w in enumerate(todo, 1):
        actor, sentence, emo, level = w.stem.split("_")
        wave = audio.load_waveform(str(w))
        res = voice.predict(wave)
        if res is None:
            continue
        p = res["probs"]
        append_csv(OUT, {
            "file": w.name, "actor": actor, "age": demo[actor]["Age"], "sex": demo[actor]["Sex"],
            "sentence": sentence, "emotion": EMOTIONS[emo], "level": level, "pred": res["label"],
            "confidence": round(res["confidence"], 4),
            "p_anger": round(p["Anger"], 4), "p_happiness": round(p["Happiness"], 4),
            "p_neutral": round(p["Neutral"], 4), "p_sadness": round(p["Sadness"], 4),
            "valence": round(fusion.valence(p), 4), "quality": round(audio.voice_quality(wave), 3),
        }, FIELDS)
        if i % 100 == 0:
            rate = i / (time.time() - t0)
            print(f"{i}/{len(todo)}  {rate:.1f} clips/s  eta {(len(todo) - i) / rate / 60:.1f} min", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
