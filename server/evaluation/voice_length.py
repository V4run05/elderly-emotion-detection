"""Does the voice reading get worse for shorter answers? Whole CREMA-D clips (no cutting) grouped by
how much speech they contain (app.analysis.audio.speech_seconds), sad vs neutral AUC per group.
(voice_short.py cuts clips instead; cut audio turned out to read very differently from whole
answers, so this is the fairer test for choosing MIN_READING_SECONDS.)

    python evaluation/voice_length.py
"""

import json

from common import DATASETS, RAW, RESULTS, mean, read_csv

from app.analysis import audio
from voice_analysis import auc

BINS = [(0.0, 0.6), (0.6, 0.9), (0.9, 1.2), (1.2, 1.6), (1.6, 9.9)]


def main():
    rows = [r for r in read_csv(RAW / "crema_voice.csv") if r["emotion"] in ("Sadness", "Neutral")]
    wav = DATASETS / "crema" / "data" / "AudioWAV"
    for i, r in enumerate(rows):
        r["speech_s"] = audio.speech_seconds(audio.load_waveform(str(wav / r["file"])))
        if i % 500 == 0:
            print(f"{i}/{len(rows)}", flush=True)
    out = {}
    for lo, hi in BINS:
        g = [r for r in rows if lo <= r["speech_s"] < hi]
        sad = [-float(r["valence"]) for r in g if r["emotion"] == "Sadness"]
        neu = [-float(r["valence"]) for r in g if r["emotion"] == "Neutral"]
        out[f"{lo}-{hi}s"] = {"n_sad": len(sad), "n_neutral": len(neu), "auc": auc(sad, neu) if sad and neu else None,
                              "mean_sad": mean(-v for v in sad), "mean_neutral": mean(-v for v in neu)}
        print(f"  speech {lo:.1f}-{hi:.1f}s  sad {len(sad):>4} neutral {len(neu):>4}  AUC {out[f'{lo}-{hi}s']['auc']}")
    (RESULTS / "voice_length.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
