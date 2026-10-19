"""Loads every local ML model once, in the background, and reports readiness.

Models are slow to load (the voice model alone takes ~15 s) but fast to run once in memory,
so the server starts immediately and warms them up on a background thread. /api/health
exposes the per-model status so clients can show a "warming up" screen.
"""

import logging
import threading
import traceback

logger = logging.getLogger("uvicorn.error")

_status = {"voice": "not_loaded", "face": "not_loaded", "text": "not_loaded"}
_errors: dict = {}
_lock = threading.Lock()

# Torch models are not guaranteed to be safe under concurrent calls; serialize inference.
inference_lock = threading.Lock()


def _loaders():
    from app.models import face, text, voice

    return {"voice": voice.load, "face": face.load, "text": text.load}


def _load_one(name: str, loader) -> None:
    with _lock:
        if _status[name] in ("loading", "ready"):
            return
        _status[name] = "loading"
    try:
        loader()
        _status[name] = "ready"
        logger.info("model '%s' ready", name)
    except Exception as exc:  # noqa: BLE001 -- report any load failure via /api/health
        _status[name] = "error"
        _errors[name] = str(exc)
        logger.error("model '%s' failed to load: %s\n%s", name, exc, traceback.format_exc())


def preload_in_background() -> None:
    def run():
        for name, loader in _loaders().items():
            _load_one(name, loader)

    threading.Thread(target=run, name="model-preload", daemon=True).start()


def ensure_loaded(name: str) -> None:
    """Block until a model is loaded (loads it on the calling thread if nobody has yet)."""
    if _status[name] == "ready":
        return
    _load_one(name, _loaders()[name])
    # Another thread may be mid-load; wait for it.
    import time

    while _status[name] == "loading":
        time.sleep(0.2)
    if _status[name] != "ready":
        raise RuntimeError(f"model '{name}' unavailable: {_errors.get(name, 'unknown error')}")


def status() -> dict:
    return {"models": dict(_status), "errors": dict(_errors), "ready": all(
        s == "ready" for s in _status.values()
    )}
