"""Analyse the CREMA-D voice results (run voice_crema.py first).

1. Accuracy of the voice model (4 classes) and how well it separates SAD from NEUTRAL (AUC).
2. Age bias: does a neutral older voice read sadder? (per-actor means, actor-level bootstrap)
3. The masking check on real readings: every clip paired with "I'm fine" words. Per message,
   fixed low line vs personal baseline (calibrated on BASELINE_SESSIONS of the actor's own neutral clips).
4. 14-day family-alert simulation per actor with real readings: a well week, then either a
   "sad week" (SAD clips, still saying fine) or a control week (more neutral/happy clips).

    python evaluation/voice_analysis.py
"""

import json
import random
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta

from common import RAW, RESULTS, bootstrap_ci, mean, pct, read_csv, wilson

from app import config
from app.analysis import baseline, masking, trends

CLASSES = ["Anger", "Happiness", "Neutral", "Sadness"]
AGE_GROUPS = [(20, 34, "20-34"), (35, 49, "35-49"), (50, 59, "50-59"), (60, 80, "60-74")]
SAYS_FINE = {"valence": 0.6}  # text-model valence of "I'm fine." (verbal_safety.py: +0.58)


def age_group(age: int) -> str:
    return next(lbl for lo, hi, lbl in AGE_GROUPS if lo <= age <= hi)


def auc(pos: list, neg: list) -> float:
    """P(score_pos > score_neg) (Mann-Whitney), ties count half."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def cluster_ci(by_actor: dict, fn, n=1000, seed=1):
    """Bootstrap over actors: resample actors with replacement, recompute fn(list of rows)."""
    actors = list(by_actor)
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        rows = [r for a in (rng.choice(actors) for _ in actors) for r in by_actor[a]]
        v = fn(rows)
        if v == v:
            vals.append(v)
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]) if vals else (float("nan"),) * 2


def classify(nonverbal: float, low: float | None) -> str:
    return masking.classify(SAYS_FINE["valence"], nonverbal, True, low)


def simulate_alerts(by_actor, rng, use_baseline: bool, episode: bool, days_well=7, days_test=7, per_day=2):
    """Returns (alerted?, day of first alert in test week or None) per actor."""
    out = {}
    start = date(2026, 1, 1)
    for actor, rows in by_actor.items():
        calm = [r for r in rows if r["emotion"] in ("Neutral", "Happiness")]
        sad = [r for r in rows if r["emotion"] == "Sadness"]
        if len(calm) < 6 or len(sad) < 4:
            continue
        sessions = []
        for d in range(days_well + days_test):
            pool = sad if (episode and d >= days_well) else calm
            picks = [rng.choice(pool) for _ in range(per_day)]
            started = datetime.combine(start + timedelta(days=d), dtime(9, 0)).astimezone()
            sessions.append({"started_at": started.isoformat(), "verbal_valence": SAYS_FINE["valence"],
                             "nonverbal_valence": mean(float(p["valence"]) for p in picks),
                             "reassurance": 1, "safety_flag": 0})
        low = baseline.compute(sessions[:config.BASELINE_SESSIONS])["low_threshold"] if use_baseline else None
        first = None
        for d in range(days_well, days_well + days_test):
            today = start + timedelta(days=d)
            series = trends.daily_series(sessions[: d + 1], 14, today, low)
            if trends.alert(series, today, today)["level"] == "alert":
                first = d - days_well + 1
                break
        out[actor] = (first is not None, first)
    return out


def main() -> None:
    rows = read_csv(RAW / "crema_voice.csv")
    for r in rows:
        r["age"] = int(r["age"])
        r["valence"] = float(r["valence"])
        r["p_sadness"] = float(r["p_sadness"])
        r["group"] = age_group(r["age"])
    by_actor = defaultdict(list)
    for r in rows:
        by_actor[r["actor"]].append(r)
    res = {"n_clips": len(rows), "n_actors": len(by_actor)}

    # ---------------- 1. accuracy
    conf = {t: {p: 0 for p in CLASSES} for t in CLASSES}
    for r in rows:
        conf[r["emotion"]][r["pred"]] += 1
    recall = {t: conf[t][t] / max(1, sum(conf[t].values())) for t in CLASSES}
    res["accuracy"] = sum(conf[t][t] for t in CLASSES) / len(rows)
    res["balanced_accuracy"] = mean(recall.values())
    res["recall"] = recall
    res["confusion"] = conf
    sad = [r for r in rows if r["emotion"] == "Sadness"]
    neu = [r for r in rows if r["emotion"] == "Neutral"]
    hap = [r for r in rows if r["emotion"] == "Happiness"]
    res["auc_sad_vs_neutral_valence"] = auc([-r["valence"] for r in sad], [-r["valence"] for r in neu])
    res["mean_valence"] = {e: mean(r["valence"] for r in rows if r["emotion"] == e) for e in CLASSES}

    # ---------------- 2. age bias
    groups = {}
    for _, _, g in AGE_GROUPS:
        g_actors = {a: rs for a, rs in by_actor.items() if rs[0]["group"] == g}
        g_rows = [r for rs in g_actors.values() for r in rs]
        g_neu = [r for r in g_rows if r["emotion"] == "Neutral"]
        g_sad = [r for r in g_rows if r["emotion"] == "Sadness"]
        groups[g] = {
            "actors": len(g_actors),
            "neutral_valence": mean(r["valence"] for r in g_neu),
            "neutral_valence_ci": cluster_ci(g_actors, lambda rs: mean(r["valence"] for r in rs if r["emotion"] == "Neutral")),
            "neutral_read_as_sad": mean(1.0 if r["pred"] == "Sadness" else 0.0 for r in g_neu),
            "sad_recall": mean(1.0 if r["pred"] == "Sadness" else 0.0 for r in g_sad),
            "auc_sad_vs_neutral": auc([-r["valence"] for r in g_sad], [-r["valence"] for r in g_neu]),
            "accuracy": mean(1.0 if r["pred"] == r["emotion"] else 0.0 for r in g_rows),
        }
    res["age_groups"] = groups
    actor_neu = [(rs[0]["age"], mean(r["valence"] for r in rs if r["emotion"] == "Neutral")) for rs in by_actor.values()]
    ages, vals = zip(*actor_neu)
    ma, mv = mean(ages), mean(vals)
    cov = sum((a - ma) * (v - mv) for a, v in actor_neu)
    r_age = cov / ((sum((a - ma) ** 2 for a in ages) * sum((v - mv) ** 2 for v in vals)) ** 0.5)
    res["corr_age_vs_neutral_valence"] = r_age
    rng = random.Random(3)
    boots = []
    for _ in range(2000):
        s = [rng.choice(actor_neu) for _ in actor_neu]
        a_, v_ = zip(*s)
        ma_, mv_ = mean(a_), mean(v_)
        num = sum((a - ma_) * (v - mv_) for a, v in s)
        den = (sum((a - ma_) ** 2 for a in a_) * sum((v - mv_) ** 2 for v in v_)) ** 0.5
        boots.append(num / den if den else 0)
    boots.sort()
    res["corr_age_vs_neutral_valence_ci"] = (boots[50], boots[1949])

    # ---------------- 3. masking check per message: fixed vs personal baseline
    rng = random.Random(5)
    per = {"fixed": defaultdict(lambda: [0, 0]), "baseline": defaultdict(lambda: [0, 0])}
    per_group = {m: {g: {"tp": [0, 0], "fp": [0, 0]} for _, _, g in AGE_GROUPS} for m in ("fixed", "baseline")}
    for actor, rs in by_actor.items():
        neu_a = [r for r in rs if r["emotion"] == "Neutral"]
        n_cal = config.BASELINE_SESSIONS
        if len(neu_a) < n_cal + 2:
            continue
        calib = rng.sample(neu_a, n_cal)
        calib_ids = {r["file"] for r in calib}
        sess = [{"started_at": f"2026-01-{i + 1:02d}T09:00:00+05:30", "nonverbal_valence": r["valence"]} for i, r in enumerate(calib)]
        low_b = baseline.compute(sess)["low_threshold"]
        g = rs[0]["group"]
        for r in rs:
            if r["file"] in calib_ids:
                continue
            for method, low in (("fixed", None), ("baseline", low_b)):
                masked = classify(r["valence"], low) == "masked"
                per[method][r["emotion"]][0] += masked
                per[method][r["emotion"]][1] += 1
                if r["emotion"] == "Sadness":
                    per_group[method][g]["tp"][0] += masked
                    per_group[method][g]["tp"][1] += 1
                if r["emotion"] in ("Neutral", "Happiness"):
                    per_group[method][g]["fp"][0] += masked
                    per_group[method][g]["fp"][1] += 1
    res["masking_per_message"] = {m: {e: {"flagged": k / n, "n": n, "ci": wilson(k, n)} for e, (k, n) in d.items()}
                                  for m, d in per.items()}
    res["masking_per_message_by_age"] = {
        m: {g: {"sad_flagged": v["tp"][0] / max(1, v["tp"][1]), "calm_flagged": v["fp"][0] / max(1, v["fp"][1])}
            for g, v in d.items()} for m, d in per_group.items()}

    # ---------------- 4. 14-day alert simulation (real readings), 20 repeats per actor
    sim = {}
    for method in ("fixed", "baseline"):
        sim[method] = {}
        for episode in (True, False):
            hits, days, by_g = 0, [], defaultdict(lambda: [0, 0])
            total = 0
            for rep in range(20):
                out = simulate_alerts(by_actor, random.Random(100 + rep), method == "baseline", episode)
                for actor, (hit, first) in out.items():
                    g = by_actor[actor][0]["group"]
                    by_g[g][0] += hit
                    by_g[g][1] += 1
                    hits += hit
                    total += 1
                    if first:
                        days.append(first)
            key = "sad_week" if episode else "control_week"
            sim[method][key] = {"alert_rate": hits / total, "ci": wilson(hits, total), "n": total,
                                "median_days_to_alert": sorted(days)[len(days) // 2] if days else None,
                                "by_age": {g: v[0] / v[1] for g, v in by_g.items()}}
    res["alert_simulation"] = sim

    (RESULTS / "voice_crema.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")

    # ---------------- print
    print(f"\nCREMA-D: {res['n_clips']} clips, {res['n_actors']} actors")
    print(f"Voice model accuracy {pct(res['accuracy'])}, balanced {pct(res['balanced_accuracy'])}; recall: " +
          ", ".join(f"{k} {pct(v)}" for k, v in recall.items()))
    print("Confusion (true -> predicted):")
    for t in CLASSES:
        print(f"  {t:<10} " + "  ".join(f"{p[:3]} {conf[t][p]:>4}" for p in CLASSES))
    print(f"Mean valence by true emotion: " + ", ".join(f"{k} {v:+.2f}" for k, v in res["mean_valence"].items()))
    print(f"AUC sad vs neutral (valence): {res['auc_sad_vs_neutral_valence']:.2f}")
    print("\nBy age group:")
    for g, s in groups.items():
        lo, hi = s["neutral_valence_ci"]
        print(f"  {g:<6} actors={s['actors']:<3} neutral valence {s['neutral_valence']:+.2f} [{lo:+.2f},{hi:+.2f}]  "
              f"neutral->sad {pct(s['neutral_read_as_sad'])}  sad recall {pct(s['sad_recall'])}  "
              f"AUC {s['auc_sad_vs_neutral']:.2f}  acc {pct(s['accuracy'])}")
    lo, hi = res["corr_age_vs_neutral_valence_ci"]
    print(f"Correlation age vs neutral valence (per actor): r = {r_age:+.2f} [{lo:+.2f},{hi:+.2f}]")
    print("\nMasking flag per message ('I'm fine' + real voice):")
    for m, d in res["masking_per_message"].items():
        print(f"  {m:<8} " + "  ".join(f"{e}: {pct(v['flagged'])}" for e, v in d.items()))
    for m, d in res["masking_per_message_by_age"].items():
        print(f"  {m:<8} by age: " + "  ".join(f"{g}: sad {pct(v['sad_flagged'])}/calm {pct(v['calm_flagged'])}" for g, v in d.items()))
    print("\n14-day alert simulation (real readings, 20 repeats x actors):")
    for m, d in sim.items():
        for k, v in d.items():
            print(f"  {m:<8} {k:<12} alert rate {pct(v['alert_rate'])} (n={v['n']})  median day {v['median_days_to_alert']}  "
                  f"by age: " + ", ".join(f"{g} {pct(x)}" for g, x in sorted(v["by_age"].items())))


if __name__ == "__main__":
    main()
