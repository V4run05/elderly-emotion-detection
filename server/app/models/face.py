"""Face emotion: trpakov/vit-face-expression (ViT, standard `transformers` checkpoint).

The model has 7 classes; we keep the 4 shared ones (angry/happy/neutral/sad) and renormalize,
dropping Disgust/Fear/Surprise mass. Faces are found first with OpenCV's YuNet detector and
cropped -- the classifier was trained on tight face crops, so running it on a whole webcam
frame gives unreliable results.

Why YuNet: the installed MediaPipe (1.x) no longer ships the old `mediapipe.python.solutions`
API, and OpenCV 5 dropped the Haar CascadeClassifier. YuNet (OpenCV's own DNN face detector,
MIT licence, 230 KB) ships in app/models/assets/ and gives a confidence score per face.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from app import config
from app.models.registry import ensure_loaded, inference_lock

LABEL_MAP = {"angry": "Anger", "happy": "Happiness", "neutral": "Neutral", "sad": "Sadness"}
YUNET_PATH = Path(__file__).parent / "assets" / "face_detection_yunet_2023mar.onnx"
DETECTION_THRESHOLD = 0.7

_processor = None
_model = None
_detector = None


def load() -> None:
    global _processor, _model, _detector
    if _model is None:
        import cv2
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        _detector = cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (320, 320),
                                              DETECTION_THRESHOLD, 0.3, 50)
        _processor = AutoImageProcessor.from_pretrained(config.FACE_MODEL_ID)
        _model = AutoModelForImageClassification.from_pretrained(config.FACE_MODEL_ID)
        _model.eval()


def detect_face(image: Image.Image) -> tuple[Image.Image, float] | None:
    """Returns (cropped largest face with a small margin, detector score), or None."""
    import cv2

    rgb = np.array(image.convert("RGB"))
    h, w = rgb.shape[:2]
    _detector.setInputSize((w, h))
    _, faces = _detector.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if faces is None or len(faces) == 0:
        return None
    x, y, fw, fh = (int(v) for v in max(faces, key=lambda f: f[2] * f[3])[:4])
    score = float(max(faces, key=lambda f: f[2] * f[3])[14])
    if fw < w * config.MIN_FACE_FRACTION:
        return None  # face too small / too far away to read
    m = int(0.15 * fw)
    x0, y0 = max(0, x - m), max(0, y - m)
    x1, y1 = min(w, x + fw + m), min(h, y + fh + m)
    return Image.fromarray(rgb[y0:y1, x0:x1]), score


def predict_frame(image: Image.Image) -> dict | None:
    """Returns {label, confidence, probs, detection_score} for one frame, or None if no face."""
    import torch

    ensure_loaded("face")
    with inference_lock:
        found = detect_face(image)
        if found is None:
            return None
        face, score = found
        inputs = _processor(images=face, return_tensors="pt")
        with torch.no_grad():
            probs = torch.softmax(_model(**inputs).logits, dim=-1)[0].tolist()

    reduced: dict = {}
    for idx, p in enumerate(probs):
        mapped = LABEL_MAP.get(_model.config.id2label[idx].lower())
        if mapped:
            reduced[mapped] = reduced.get(mapped, 0.0) + p
    total = sum(reduced.values())
    if total <= 0:
        return None
    reduced = {k: v / total for k, v in reduced.items()}
    label = max(reduced, key=reduced.get)
    return {"label": label, "confidence": reduced[label], "probs": reduced,
            "detection_score": score}


def predict_frames(images: list) -> dict | None:
    """Averages predictions over several frames from one answer. Quality = share of frames
    with a face x mean detector score. Returns None if no frame had a face."""
    results = [r for r in (predict_frame(img) for img in images) if r is not None]
    if not results:
        return None
    probs = {c: float(np.mean([r["probs"].get(c, 0.0) for r in results])) for c in config.CLASSES}
    label = max(probs, key=probs.get)
    return {
        "label": label,
        "confidence": probs[label],
        "probs": probs,
        "quality": (len(results) / len(images)) * float(np.mean([r["detection_score"] for r in results])),
        "frames_used": len(results),
        "frames_total": len(images),
    }
