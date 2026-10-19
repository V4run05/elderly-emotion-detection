"""Voice emotion: autrainer/msp-podcast-emo-class-big4-w2v2-l-emo (wav2vec2-large, audEERING).

Trained on MSP-Podcast (real, spontaneous speech -- not acted), 4 classes:
Anger / Happiness / Neutral / Sadness. Inference only, no training.

This checkpoint is in autrainer's own format (YAML configs + `_best/model.pt`), NOT a plain
`transformers` checkpoint, so `AutoModel.from_pretrained` does not work. We use autrainer's
Python `Inference` class in-process: ~15 s to load once, then ~0.3 s per clip. (The previous
prototype shelled out to the `autrainer inference` CLI per request, which reloaded the model
every time and took ~36 s per check-in.)
"""

import glob
import os
import tempfile

import numpy as np

from app import config
from app.models.registry import ensure_loaded, inference_lock

CLASS_CODES = {"A": "Anger", "H": "Happiness", "N": "Neutral", "S": "Sadness"}

_inference = None


def _local_model_dir() -> str:
    """Use the already-downloaded copy if present (skips a slow Hugging Face API round trip),
    otherwise let autrainer download it."""
    import torch

    cache_root = os.path.join(
        torch.hub.get_dir(), "autrainer", config.VOICE_MODEL_ID.replace("/", "--") + "--main"
    )
    found = glob.glob(os.path.join(cache_root, "**", "model.yaml"), recursive=True)
    if found:
        return os.path.dirname(found[0])

    from autrainer.serving.model_paths import get_model_path

    return get_model_path(f"hf:{config.VOICE_MODEL_ID}", False)


def load() -> None:
    global _inference
    if _inference is None:
        from autrainer.serving import Inference

        _inference = Inference(_local_model_dir(), device="cpu")


def predict(waveform: np.ndarray, sample_rate: int = 16000) -> dict | None:
    """Returns {label, confidence, probs} for a 16 kHz mono waveform, or None if the clip
    couldn't be scored (empty/too short)."""
    import soundfile as sf

    ensure_loaded("voice")
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        sf.write(wav_path, waveform, sample_rate)
        with inference_lock:
            result = _inference.predict_file(wav_path)
    finally:
        os.remove(wav_path)

    if result is None:
        return None
    _prediction, _output, code_probs = result
    probs = {CLASS_CODES[c]: float(p) for c, p in code_probs.items() if c in CLASS_CODES}
    label = max(probs, key=probs.get)
    return {"label": label, "confidence": probs[label], "probs": probs}
