import pytest

from app.analysis import fusion


def ch(label_probs: dict, quality: float) -> dict:
    label = max(label_probs, key=label_probs.get)
    probs = {"Anger": 0.0, "Happiness": 0.0, "Neutral": 0.0, "Sadness": 0.0, **label_probs}
    return {"label": label, "confidence": probs[label], "probs": probs, "quality": quality}


def test_valence_mapping():
    assert fusion.valence({"Happiness": 1.0}) == 1.0
    assert fusion.valence({"Sadness": 1.0}) == -1.0
    assert fusion.valence({"Neutral": 1.0}) == 0.0
    assert fusion.valence({"Anger": 1.0}) == -0.5


def test_weights_follow_quality_times_confidence():
    voice = ch({"Sadness": 0.8, "Neutral": 0.2}, quality=1.0)   # 0.8
    face = ch({"Neutral": 0.6, "Happiness": 0.4}, quality=0.5)  # 0.3
    out = fusion.fuse({"voice": voice, "face": face})
    assert out["weights"]["voice"] == pytest.approx(0.8 / 1.1)
    assert out["weights"]["face"] == pytest.approx(0.3 / 1.1)
    assert out["probs"]["Sadness"] == pytest.approx(0.8 / 1.1 * 0.8)
    assert out["label"] == "Sadness"
    assert sum(out["probs"].values()) == pytest.approx(1.0)


def test_missing_channel_drops_out():
    voice = ch({"Happiness": 0.9, "Neutral": 0.1}, quality=0.9)
    out = fusion.fuse({"voice": voice, "face": None})
    assert out["weights"] == {"voice": 1.0}
    assert out["available"]


def test_nothing_usable_returns_neutral():
    out = fusion.fuse({"voice": None, "face": ch({"Sadness": 1.0}, quality=0.0)})
    assert not out["available"]
    assert out["valence"] == 0.0
