"""Personal baseline: judge "seems low" against the person's own normal, not a fixed number.

Why: the voice and face models were trained mostly on younger, expressive faces/voices. For an
older person the same models can read *every* day as flat (≈0) or even sad (<0). A fixed
"low" line (-0.20) then either never fires (flat person) or always fires (sad-reading person).

How:
- Calibration: the first BASELINE_SESSIONS analysed check-ins (default 5).
- normal  = median non-verbal valence of those sessions
- spread  = robust spread (1.4826 x median absolute deviation)
- low line = normal - max(BASELINE_MIN_DROP, BASELINE_SPREAD_K x spread), capped at
  BASELINE_MAX_LOW_LINE (never call a clearly positive reading "low").
Until calibration is complete the fixed LOW_NONVERBAL_THRESHOLD is used.

Limitation: if the person is already low during calibration, that becomes their "normal".
Reset by clearing history (see docs/PROJECT_SPEC.md, open questions).
"""

from statistics import median

from app import config


def compute(sessions: list) -> dict:
    """sessions: any order; uses the earliest analysed ones. Returns the baseline description."""
    analysed = sorted((s for s in sessions if s.get("nonverbal_valence") is not None),
                      key=lambda s: s["started_at"])
    needed = config.BASELINE_SESSIONS
    calib = [s["nonverbal_valence"] for s in analysed[:needed]]
    fixed = config.LOW_NONVERBAL_THRESHOLD
    if not config.BASELINE_ENABLED or len(calib) < needed:
        return {"enabled": config.BASELINE_ENABLED, "ready": False, "sessions": len(calib),
                "needed": needed, "normal": None, "spread": None, "low_threshold": fixed}
    normal = median(calib)
    spread = 1.4826 * median(abs(v - normal) for v in calib)
    drop = max(config.BASELINE_MIN_DROP, config.BASELINE_SPREAD_K * spread)
    low = min(config.BASELINE_MAX_LOW_LINE, normal - drop)
    return {"enabled": True, "ready": True, "sessions": len(calib), "needed": needed,
            "normal": round(normal, 3), "spread": round(spread, 3), "low_threshold": round(low, 3)}
