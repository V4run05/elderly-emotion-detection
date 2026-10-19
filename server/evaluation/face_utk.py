"""Face model age-bias probe on UTKFace (age-labelled face crops, no expression labels).

For a stratified sample per age band: run the expression model on the face crop and record the
4-class probabilities, valence, and whether the YuNet detector finds the face. If the model reads
older faces as sadder/flatter, mean valence and P(sad) drift with age. Caveat: UTKFace has no
expression labels, so real expression differences between age groups (e.g. fewer smiles in photos
of older people) are mixed in with model bias.

    python evaluation/face_utk.py [--per-band 250]
"""

import argparse
import json
import random
from collections import defaultdict

from PIL import Image

from common import DATASETS, RAW, RESULTS, append_csv, bootstrap_ci, mean, pct, read_csv

from app.analysis import fusion
from app.models import face, registry

BANDS = [(20, 29), (30, 39), (40, 49), (50, 59), (60, 69), (70, 79), (80, 99)]
OUT = RAW / "utk_face.csv"
FIELDS = ["file", "age", "band", "detected", "p_anger", "p_happiness", "p_neutral", "p_sadness", "valence", "pred"]


def classify_crop(img):
    import torch
    with registry.inference_lock:
        inputs = face._processor(images=img, return_tensors="pt")
        with torch.no_grad():
            probs = torch.softmax(face._model(**inputs).logits, dim=-1)[0].tolist()
    reduced = {}
    for i, p in enumerate(probs):
        m = face.LABEL_MAP.get(face._model.config.id2label[i].lower())
        if m:
            reduced[m] = reduced.get(m, 0.0) + p
    tot = sum(reduced.values())
    return {k: v / tot for k, v in reduced.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-band", type=int, default=250)
    args = ap.parse_args()
    registry.ensure_loaded("face")
    files = list((DATASETS / "utk" / "UTKFace").glob("*.jpg"))
    by_band = defaultdict(list)
    for f in files:
        try:
            age = int(f.name.split("_")[0])
        except ValueError:
            continue
        for lo, hi in BANDS:
            if lo <= age <= hi:
                by_band[f"{lo}-{hi}"].append((f, age))
    rng = random.Random(7)
    done = {r["file"] for r in read_csv(OUT)} if OUT.exists() else set()
    for band, items in by_band.items():
        sample = rng.sample(items, min(args.per_band, len(items)))
        for f, age in sample:
            if f.name in done:
                continue
            img = Image.open(f).convert("RGB")
            probs = classify_crop(img)
            detected = face.detect_face(img.resize((img.width * 2, img.height * 2))) is not None
            append_csv(OUT, {"file": f.name, "age": age, "band": band, "detected": int(detected),
                             **{f"p_{k.lower()}": round(v, 4) for k, v in probs.items()},
                             "valence": round(fusion.valence(probs), 4), "pred": max(probs, key=probs.get)}, FIELDS)
        print(f"{band}: done ({len(sample)})", flush=True)

    rows = read_csv(OUT)
    summary = {}
    for lo, hi in BANDS:
        b = f"{lo}-{hi}"
        rs = [r for r in rows if r["band"] == b]
        vals = [float(r["valence"]) for r in rs]
        summary[b] = {"n": len(rs), "mean_valence": mean(vals), "valence_ci": bootstrap_ci(vals),
                      "p_sad": mean(float(r["p_sadness"]) for r in rs),
                      "p_happy": mean(float(r["p_happiness"]) for r in rs),
                      "pred_sad": mean(1.0 if r["pred"] == "Sadness" else 0.0 for r in rs),
                      "pred_neutral": mean(1.0 if r["pred"] == "Neutral" else 0.0 for r in rs),
                      "detected": mean(float(r["detected"]) for r in rs)}
        flat = [r for r in rs if float(r["p_happiness"]) < 0.2]   # not smiling: where age bias shows
        summary[b]["not_smiling"] = {"n": len(flat), "mean_valence": mean(float(r["valence"]) for r in flat),
                                     "p_sad": mean(float(r["p_sadness"]) for r in flat),
                                     "pred_sad": mean(1.0 if r["pred"] == "Sadness" else 0.0 for r in flat)}
    (RESULTS / "face_utk.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print("\nFace model on UTKFace by age band:")
    for b, s in summary.items():
        print(f"  {b:<6} n={s['n']:<4} valence {s['mean_valence']:+.2f} [{s['valence_ci'][0]:+.2f},{s['valence_ci'][1]:+.2f}]  "
              f"P(sad) {s['p_sad']:.2f}  P(happy) {s['p_happy']:.2f}  pred sad {pct(s['pred_sad'])}  "
              f"pred neutral {pct(s['pred_neutral'])}  face detected {pct(s['detected'])}")
    print("Not smiling (P(happy) < 0.2):")
    for b, s in summary.items():
        f = s["not_smiling"]
        print(f"  {b:<6} n={f['n']:<4} valence {f['mean_valence']:+.2f}  P(sad) {f['p_sad']:.2f}  read as sad {pct(f['pred_sad'])}")


if __name__ == "__main__":
    main()
