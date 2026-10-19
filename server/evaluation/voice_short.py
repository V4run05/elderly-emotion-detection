"""Are very short answers ("hmm", "yes") reliable voice readings? Cut CREMA-D clips to the first
0.4 / 0.6 / 0.8 / 1.0 s of SPEECH (from speech onset, app.analysis.audio.speech_span) and check how
well sad and neutral still separate (AUC), vs the whole clip. (A first version cut from the start
of the file, which includes up to 1.3 s of leading silence.)

    python evaluation/voice_short.py [--per-class 250]
"""

import argparse
import json
import random

from common import DATASETS, RESULTS, mean

from app.analysis import audio, fusion
from app.models import registry, voice
from voice_analysis import auc

SR = 16000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=250)
    args = ap.parse_args()
    registry.ensure_loaded("voice")
    wav_dir = DATASETS / "crema" / "data" / "AudioWAV"
    rng = random.Random(4)
    clips = {e: rng.sample(sorted(wav_dir.glob(f"*_{e}_*.wav")), args.per_class) for e in ("SAD", "NEU")}
    durations = [0.4, 0.6, 0.8, 1.0, None]
    vals = {d: {"SAD": [], "NEU": []} for d in durations}
    for e, files in clips.items():
        for i, f in enumerate(files):
            w = audio.load_waveform(str(f))
            span = audio.speech_span(w)
            if span is None:
                continue
            for d in durations:
                seg = w if d is None else w[span[0]: min(span[1], span[0] + int(d * SR))]
                r = voice.predict(seg)
                if r:
                    vals[d][e].append(fusion.valence(r["probs"]))
            if i % 50 == 0:
                print(f"{e} {i}/{len(files)}", flush=True)
    out = {}
    for d in durations:
        key = "full" if d is None else f"{d}s speech"
        out[key] = {"auc_sad_vs_neutral": auc([-v for v in vals[d]["SAD"]], [-v for v in vals[d]["NEU"]]),
                    "mean_sad": mean(vals[d]["SAD"]), "mean_neutral": mean(vals[d]["NEU"])}
    (RESULTS / "voice_short.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for k, v in out.items():
        print(f"  {k:<12} AUC {v['auc_sad_vs_neutral']:.2f}  sad {v['mean_sad']:+.2f}  neutral {v['mean_neutral']:+.2f}")


if __name__ == "__main__":
    main()
