"""Per-channel vs fused personal baseline when the camera is not always on (run voice_crema.py and
face_utk.py first).

Every simulated answer pairs a real CREMA-D voice reading with a real UTKFace reading of a person
aged 60+ (fused exactly like the app does). Per actor, 14 days: a well week (calm voice), then a
sad week (sad voice, face kept normal: masking) or a control week (calm voice again).
Camera conditions: always on; on during calibration then off on half the days; off during
calibration then on. Compares the fused baseline (one number) with the per-channel baseline.

    python evaluation/channel_sim.py [--reps 10]
"""

import argparse
import json
import random
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta

from common import RAW, RESULTS, mean, pct, read_csv

from app import config
from app.analysis import baseline, fusion, trends

CLASSES = ["Anger", "Happiness", "Neutral", "Sadness"]


def channel(row, quality):
    probs = {c: float(row[f"p_{c.lower()}"]) for c in CLASSES}
    label = max(probs, key=probs.get)
    return {"label": label, "confidence": probs[label], "probs": probs, "quality": quality}


def simulate(by_actor, faces, rng, method, camera, episode, per_day, days_well=7, days_test=7):
    out = []
    start = date(2026, 1, 1)
    for actor, rows in by_actor.items():
        calm = [r for r in rows if r["emotion"] in ("Neutral", "Happiness")]
        sad = [r for r in rows if r["emotion"] == "Sadness"]
        if len(calm) < 6 or len(sad) < 4:
            continue
        sessions = []
        for d in range(days_well + days_test):
            calibrating = d < config.BASELINE_SESSIONS
            cam = {"always": True, "intermittent": calibrating or rng.random() < 0.5,
                   "late": not calibrating}[camera]
            pool = sad if (episode and d >= days_well) else calm
            fused, voices, face_vals = [], [], []
            for _ in range(per_day):
                v = channel(rng.choice(pool), 0.9)
                f = channel(rng.choice(faces), 0.9) if cam else None
                fz = fusion.fuse({"voice": v, "face": f})
                fused.append(fz["valence"])
                voices.append(fusion.valence(v["probs"]))
                if f:
                    face_vals.append(fusion.valence(f["probs"]))
            started = datetime.combine(start + timedelta(days=d), dtime(9, 0)).astimezone()
            s = {"started_at": started.isoformat(), "verbal_valence": 0.6, "nonverbal_valence": mean(fused),
                 "reassurance": 1, "safety_flag": 0, "readings": per_day}
            if method == "channels":
                s.update(voice_valence=mean(voices), face_valence=mean(face_vals) if face_vals else None)
            sessions.append(s)
        base = baseline.compute(sessions[:config.BASELINE_SESSIONS])
        hit = False
        for d in range(days_well, days_well + days_test):
            today = start + timedelta(days=d)
            series = trends.daily_series(sessions[: d + 1], 14, today, base=base)
            if trends.alert(series, today, today)["level"] == "alert":
                hit = True
                break
        out.append(hit)
    return mean(out), len(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--per-day", type=int, default=3)
    args = ap.parse_args()
    rows = read_csv(RAW / "crema_voice.csv")
    by_actor = defaultdict(list)
    for r in rows:
        by_actor[r["actor"]].append(r)
    faces = [r for r in read_csv(RAW / "utk_face.csv") if int(r["age"]) >= 60]
    res = {}
    methods = [("fused", "mean"), ("channels", "mean"), ("channels", "any"), ("channels", "voice")]
    for camera in ("always", "intermittent", "late"):
        for method, combine in methods:
            config.BASELINE_COMBINE = combine
            cell = {}
            for episode in (True, False):
                vals = [simulate(by_actor, faces, random.Random(300 + k), method, camera, episode, args.per_day)[0]
                        for k in range(args.reps)]
                cell["sad_week" if episode else "control_week"] = mean(vals)
            label = method if method == "fused" else f"{method}/{combine}"
            res[f"{camera}/{label}"] = cell
            print(f"  camera {camera:<12} {label:<14} sad week caught {pct(cell['sad_week'])}   "
                  f"false alerts {pct(cell['control_week'])}", flush=True)
    config.BASELINE_COMBINE = "voice"
    sweep = {}
    defaults = (config.BASELINE_SPREAD_K, config.BASELINE_SESSIONS, config.BASELINE_COMBINE)
    for k in (1.5, 2.0):
        for calib in (5, 7):
            config.BASELINE_SPREAD_K, config.BASELINE_SESSIONS = k, calib
            cell = {}
            for episode in (True, False):
                vals = [simulate(by_actor, faces, random.Random(400 + j), "channels", "intermittent", episode,
                                 args.per_day)[0] for j in range(max(3, args.reps // 2))]
                cell["sad_week" if episode else "control_week"] = mean(vals)
            sweep[f"k={k} calib={calib}"] = cell
            print(f"  channels/voice, intermittent camera, k={k} calib={calib}: sad {pct(cell['sad_week'])}   "
                  f"false {pct(cell['control_week'])}", flush=True)
    config.BASELINE_SPREAD_K, config.BASELINE_SESSIONS, config.BASELINE_COMBINE = defaults
    res["settings_sweep"] = sweep
    (RESULTS / "channel_sim.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
