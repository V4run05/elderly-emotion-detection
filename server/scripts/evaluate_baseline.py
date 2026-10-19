"""Simulation: fixed "low" line vs personal baseline (analysis/baseline.py).

Synthetic people whose voice/face readings sit at different "normal" levels, as the models
might see them (expressive, flat, or reading sad because of age bias). Everyone keeps SAYING
they're fine. Half stay well; the other half quietly drop by --drop after week 1.

    python scripts/evaluate_baseline.py                 # 300 people per group, drop 0.25
    python scripts/evaluate_baseline.py --drop 0.15 --people 500

Reported per method (days 8-21, after a 7-day calibration week):
    false flags   share of WELL days classified low/masked            (lower is better)
    detected      share of EPISODE days classified low/masked         (higher is better)
    false alerts  share of WELL people who got an "alert" at any point (lower is better)
    alerted       share of EPISODE people who got an "alert"           (higher is better)

This is a synthetic check of the decision logic only, not evidence about real people.
"""

import argparse
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analysis import baseline, trends  # noqa: E402

PROFILES = {  # name: (normal non-verbal valence, day-to-day spread)
    "expressive": (0.30, 0.12),
    "flat": (0.00, 0.06),
    "reads sad": (-0.30, 0.08),
}
DAYS = 21
CALIBRATION_DAYS = 7
START = date(2026, 1, 1)


def clip(v: float) -> float:
    return max(-1.0, min(1.0, v))


def simulate_person(rng: random.Random, normal: float, spread: float, drop: float) -> list:
    sessions = []
    for d in range(DAYS):
        mean = normal - (drop if d >= CALIBRATION_DAYS else 0.0)
        started = datetime.combine(START + timedelta(days=d), time(9, 0)).astimezone()
        sessions.append({
            "started_at": started.isoformat(),
            "verbal_valence": clip(rng.gauss(0.6, 0.15)),     # always "I'm fine"
            "nonverbal_valence": clip(rng.gauss(mean, spread)),
            "reassurance": int(rng.random() < 0.7),
            "safety_flag": 0,
        })
    return sessions


def score(sessions: list, low_threshold) -> tuple:
    """Returns (flagged eval days, eval days, ever alerted)."""
    flagged, total, alerted = 0, 0, False
    for d in range(CALIBRATION_DAYS, DAYS):
        today = START + timedelta(days=d)
        upto = sessions[: d + 1]
        series = trends.daily_series(upto, 14, today, low_threshold)
        if series[-1]["status"] in ("low", "masked"):
            flagged += 1
        total += 1
        if trends.alert(series, today, today)["level"] == "alert":
            alerted = True
    return flagged, total, alerted


def run(people: int, drop: float, seed: int) -> list:
    rows = []
    for name, (normal, spread) in PROFILES.items():
        rng = random.Random(seed)
        acc = {m: {"ff": 0, "fd": 0, "det": 0, "dd": 0, "fa": 0, "al": 0} for m in ("fixed", "baseline")}
        for _ in range(people):
            for episode in (False, True):
                sessions = simulate_person(rng, normal, spread, drop if episode else 0.0)
                b = baseline.compute(sessions[:CALIBRATION_DAYS])
                for method, low in (("fixed", None), ("baseline", b["low_threshold"])):
                    f, t, a = score(sessions, low)
                    m = acc[method]
                    if episode:
                        m["det"] += f; m["dd"] += t; m["al"] += a
                    else:
                        m["ff"] += f; m["fd"] += t; m["fa"] += a
        for method, m in acc.items():
            rows.append((name, method, m["ff"] / m["fd"], m["det"] / m["dd"], m["fa"] / people, m["al"] / people))
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--people", type=int, default=300)
    p.add_argument("--drop", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    from app import config
    config.BASELINE_ENABLED = True  # evaluate even if switched off in .env

    print(f"\nDrop after week 1: {args.drop:+.2f}   people per group: {args.people}\n")
    print(f"{'profile':<12}{'method':<10}{'false flags':>13}{'detected':>10}{'false alerts':>14}{'alerted':>9}")
    for name, method, ff, det, fa, al in run(args.people, args.drop, args.seed):
        print(f"{name:<12}{method:<10}{ff:>12.0%}{det:>10.0%}{fa:>14.0%}{al:>9.0%}")


if __name__ == "__main__":
    main()
