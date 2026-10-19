"""Fuses the non-verbal channels (voice tone + facial expression) into one distribution.

Weight of each channel: w_i = (quality_i * confidence_i) / sum_j(quality_j * confidence_j),
then a per-class weighted average. A channel that is missing (no face in frame, silent clip)
simply drops out. The earlier prototype's 2.5x "salience boost" for non-Neutral labels is
deliberately NOT used: it pushes readings away from Neutral, which would inflate false
"masked" flags in this project.
"""

from app import config

NEUTRAL = {c: (1.0 if c == "Neutral" else 0.0) for c in config.CLASSES}


def valence(probs: dict) -> float:
    """Probability-weighted valence in [-1, 1] for a 4-class distribution."""
    return float(sum(config.CLASS_VALENCE[c] * probs.get(c, 0.0) for c in config.CLASSES))


def fuse(channels: dict) -> dict:
    """channels: {name: {label, confidence, probs, quality} or None}.
    Returns {label, confidence, probs, valence, weights, available}."""
    usable = {
        name: ch for name, ch in channels.items()
        if ch is not None and ch.get("quality", 0) > 0
    }
    if not usable:
        return {"label": "Neutral", "confidence": 0.0, "probs": dict(NEUTRAL), "valence": 0.0,
                "weights": {}, "available": False}

    raw = {name: ch["quality"] * ch["confidence"] for name, ch in usable.items()}
    total = sum(raw.values())
    weights = ({n: v / total for n, v in raw.items()} if total > 0
               else {n: 1.0 / len(usable) for n in usable})

    probs = {c: sum(weights[n] * usable[n]["probs"].get(c, 0.0) for n in usable)
             for c in config.CLASSES}
    label = max(probs, key=probs.get)
    return {"label": label, "confidence": probs[label], "probs": probs,
            "valence": valence(probs), "weights": weights, "available": True}
