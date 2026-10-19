"""What would make the voice side detect a low week better? (run voice_crema.py first)

Compares, on real CREMA-D readings:
- which voice score separates sad from neutral best (valence, P(sad), P(sad)-P(happy)), per clip
  and after normalising each actor against their own neutral clips (what a personal baseline does)
- how many spoken answers per day are needed (averaging more answers per day)
- the baseline's settings (BASELINE_SPREAD_K, BASELINE_MIN_DROP, calibration sessions)
for the 14-day alert simulation (well week, then a sad week vs a control week).

    python evaluation/voice_tuning.py
"""

import json
import random
from collections import defaultdict
from statistics import median

from common import RAW, RESULTS, mean, pct, read_csv

from app import config
from voice_analysis import auc, simulate_alerts


def main() -> None:
    rows = read_csv(RAW / "crema_voice.csv")
    for r in rows:
        for k in ("valence", "p_sadness", "p_happiness", "p_neutral", "p_anger"):
            r[k] = float(r[k])
    by_actor = defaultdict(list)
    for r in rows:
        by_actor[r["actor"]].append(r)
    res = {"scores": {}, "per_day": {}, "settings": {}}

    scores = {"valence": lambda r: -r["valence"], "p_sad": lambda r: r["p_sadness"],
              "p_sad_minus_p_happy": lambda r: r["p_sadness"] - r["p_happiness"]}
    for name, f in scores.items():
        sad = [f(r) for r in rows if r["emotion"] == "Sadness"]
        neu = [f(r) for r in rows if r["emotion"] == "Neutral"]
        # per-actor normalisation: subtract the actor's median neutral score
        sad_n, neu_n = [], []
        for rs in by_actor.values():
            ref = median(f(r) for r in rs if r["emotion"] == "Neutral")
            sad_n += [f(r) - ref for r in rs if r["emotion"] == "Sadness"]
            neu_n += [f(r) - ref for r in rs if r["emotion"] == "Neutral"]
        res["scores"][name] = {"auc": auc(sad, neu), "auc_actor_normalised": auc(sad_n, neu_n)}

    def run(use_baseline=True, per_day=2, reps=10):
        out = {}
        for episode in (True, False):
            hits = total = 0
            days = []
            for rep in range(reps):
                for hit, first in simulate_alerts(by_actor, random.Random(200 + rep), use_baseline, episode,
                                                  per_day=per_day).values():
                    hits += hit
                    total += 1
                    if first:
                        days.append(first)
            out["sad_week" if episode else "control_week"] = {"alert_rate": hits / total,
                                                               "median_day": sorted(days)[len(days) // 2] if days else None}
        return out

    for k in (1, 2, 4, 6):
        res["per_day"][k] = {"fixed": run(False, k), "baseline": run(True, k)}

    defaults = (config.BASELINE_SPREAD_K, config.BASELINE_MIN_DROP, config.BASELINE_SESSIONS)
    for spread_k in (1.0, 1.5, 2.0):
        for min_drop in (0.08, 0.12):
            for sessions in (5, 7):
                config.BASELINE_SPREAD_K, config.BASELINE_MIN_DROP, config.BASELINE_SESSIONS = spread_k, min_drop, sessions
                res["settings"][f"k={spread_k} drop={min_drop} calib={sessions}"] = run(True, 2, reps=6)
    config.BASELINE_SPREAD_K, config.BASELINE_MIN_DROP, config.BASELINE_SESSIONS = defaults

    (RESULTS / "voice_tuning.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nSad vs neutral separation (AUC, 0.5 = chance):")
    for n, s in res["scores"].items():
        print(f"  {n:<22} raw {s['auc']:.2f}   normalised per person {s['auc_actor_normalised']:.2f}")
    print("\nAnswers per day -> alert rate in sad week / control week:")
    for k, d in res["per_day"].items():
        print(f"  {k} per day: fixed {pct(d['fixed']['sad_week']['alert_rate'])}/{pct(d['fixed']['control_week']['alert_rate'])}   "
              f"baseline {pct(d['baseline']['sad_week']['alert_rate'])}/{pct(d['baseline']['control_week']['alert_rate'])} "
              f"(median day {d['baseline']['sad_week']['median_day']})")
    print("\nBaseline settings (2 answers/day) -> sad week / control week:")
    for k, d in res["settings"].items():
        print(f"  {k:<28} {pct(d['sad_week']['alert_rate'])} / {pct(d['control_week']['alert_rate'])}  median day {d['sad_week']['median_day']}")


if __name__ == "__main__":
    main()
