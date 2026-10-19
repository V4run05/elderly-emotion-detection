"""Personal baseline: judge "seems low" against the person's own normal, not a fixed number.

Why (measured, docs/EVALUATION.md §3-4): the voice model reads neutral speech at about -0.34, and
the face model reads non-smiling older faces as sad about twice as often as younger ones. A fixed
line either fires all the time or never, depending on the person.

How:
- A separate baseline per channel (voice, face), each from the first BASELINE_SESSIONS
  conversations that had a reading on that channel. Separate, because the two channels sit at
  very different levels (voice around -0.3, face around +0.3): with one fused baseline, turning the
  camera off or the face not being found moves the score although nothing changed.
- normal = median of those sessions, spread = 1.4826 x median absolute deviation
- A reading is turned into "compared with normal": the mean over the calibrated channels present
  of (reading - normal). Low means at or below -drop, drop = max(BASELINE_MIN_DROP,
  BASELINE_SPREAD_K x spread) (averaged over the channels used).
- The masking rule (analysis/masking.py) then runs on that relative value, so the person's
  normal counts as 0.
Until a channel is calibrated, the fixed LOW_NONVERBAL_THRESHOLD is used on the fused value
("learning"). Old data without per-channel values falls back to one fused baseline ("fused").

Limitation: if the person is already low during calibration, that becomes their "normal".
"""

from statistics import mean, median

from app import config

CHANNELS = ("voice", "face")


def _stats(values: list) -> tuple[float, float]:
    normal = median(values)
    return normal, 1.4826 * median(abs(v - normal) for v in values)


def _drop(spread: float) -> float:
    return max(config.BASELINE_MIN_DROP, config.BASELINE_SPREAD_K * spread)


def compute(sessions: list) -> dict:
    """sessions: any order; uses the earliest analysed ones. Returns the baseline description.
    Keys kept from the fused version: enabled, ready, sessions, needed, normal, spread, low_threshold."""
    analysed = sorted((s for s in sessions if s.get("nonverbal_valence") is not None),
                      key=lambda s: s["started_at"])
    needed = config.BASELINE_SESSIONS
    fixed = config.LOW_NONVERBAL_THRESHOLD
    enabled = config.BASELINE_ENABLED
    channels = {}
    for c in CHANNELS:
        vals = [s[f"{c}_valence"] for s in analysed if s.get(f"{c}_valence") is not None][:needed]
        if enabled and len(vals) >= needed:
            normal, spread = _stats(vals)
            channels[c] = {"ready": True, "sessions": needed, "normal": round(normal, 3),
                           "spread": round(spread, 3), "drop": round(_drop(spread), 3)}
        else:
            channels[c] = {"ready": False, "sessions": len(vals)}
    calib = [s["nonverbal_valence"] for s in analysed[:needed]]
    out = {"enabled": enabled, "needed": needed, "channels": channels, "fixed_low_threshold": fixed,
           "sessions": max([len(calib)] + [ch["sessions"] for ch in channels.values()])}
    if any(ch["ready"] for ch in channels.values()):
        # low_threshold here is on the "compared with normal" scale (normal = 0)
        drops = [ch["drop"] for ch in channels.values() if ch["ready"]]
        return {**out, "ready": True, "mode": "channels", "normal": None, "spread": None,
                "low_threshold": round(-mean(drops), 3)}
    if enabled and len(calib) >= needed and not any(s.get("voice_valence") is not None for s in analysed):
        normal, spread = _stats(calib)   # old data: one fused baseline, as before
        low = min(config.BASELINE_MAX_LOW_LINE, normal - _drop(spread))
        return {**out, "ready": True, "mode": "fused", "normal": round(normal, 3), "spread": round(spread, 3),
                "low_threshold": round(low, 3)}
    return {**out, "ready": False, "mode": "learning", "normal": None, "spread": None, "low_threshold": fixed}


def judge(base: dict, fused: float | None, voice: float | None = None, face: float | None = None) -> dict:
    """The value the masking rule should use for one reading (a message, a session or a day).
    Returns {value, low_threshold, relative}: relative=True means value is "compared with
    normal" (normal = 0); otherwise it is the fused valence against a fixed/fused line."""
    if base.get("mode") == "channels":
        used = [(v - base["channels"][c]["normal"], base["channels"][c]["drop"])
                for c, v in (("voice", voice), ("face", face))
                if v is not None and base["channels"][c]["ready"]]
        if config.BASELINE_COMBINE == "voice" and base["channels"]["voice"]["ready"] and voice is not None:
            used = used[:1]
        if used:
            if config.BASELINE_COMBINE == "mean":
                dev, drop = mean(d for d, _ in used), mean(x for _, x in used)
            else:   # "any": the channel furthest below its own normal (relative to its drop) decides
                dev, drop = min(used, key=lambda u: u[0] / u[1])
            return {"value": round(dev, 3), "low_threshold": round(-drop, 3), "relative": True}
        # a reading only on an uncalibrated channel: fixed line on the fused value
        return {"value": fused, "low_threshold": base["fixed_low_threshold"], "relative": False}
    return {"value": fused, "low_threshold": base["low_threshold"], "relative": False}
