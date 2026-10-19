"""Verbal sentiment: cardiffnlp/twitter-roberta-base-sentiment-latest (negative/neutral/positive).

This scores what the person *claims*. Chosen over a 7-class text-emotion model
(j-hartmann/emotion-english-distilroberta-base) after testing: that model rated
"I'm fine, nothing to worry about." as 67% *fear* (keyed on "worry"), which is exactly the
reassurance phrase this project needs to read as positive. The sentiment model rates it
74% positive. Verbal valence = P(positive) - P(negative), in [-1, 1].
"""

from app import config
from app.models.registry import ensure_loaded, inference_lock

_pipeline = None


def load() -> None:
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline

        _pipeline = pipeline("text-classification", model=config.TEXT_MODEL_ID, top_k=None)


def predict(text: str) -> dict:
    """Returns {valence, probs: {positive, neutral, negative}}."""
    ensure_loaded("text")
    with inference_lock:
        scores = _pipeline(text[:1000])[0]
    probs = {s["label"].lower(): float(s["score"]) for s in scores}
    valence = probs.get("positive", 0.0) - probs.get("negative", 0.0)
    return {"valence": valence, "probs": probs}
