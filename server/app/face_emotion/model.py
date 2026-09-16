"""Loads and runs the pretrained facial emotion recognition model.

Model: trpakov/vit-face-expression (Hugging Face) -- a ViT image classifier fine-tuned on
FER2013+, a standard `transformers` checkpoint (unlike the audio model). No training step --
this only runs inference. Outputs 7 classes: Angry, Disgust, Fear, Happy, Sad, Surprise,
Neutral.

The voice model only has 4 classes (Anger, Happiness, Neutral, Sadness), so to fuse the two
signals we map/reduce the face model's output down to that same 4-class taxonomy: Disgust,
Fear, and Surprise probability mass is dropped and the remaining 4 classes are renormalized to
sum to 1. This is a deliberate simplification, not a claim that those emotions don't exist --
documented in docs/IMPLEMENTATION_NOTES.md.
"""

from PIL import Image
import numpy as np

MODEL_ID = "trpakov/vit-face-expression"

# Face model's native label -> our shared 4-class taxonomy. Classes absent from this mapping
# (Disgust, Fear, Surprise) are dropped and the rest renormalized.
LABEL_MAP = {
    "angry": "Anger",
    "happy": "Happiness",
    "neutral": "Neutral",
    "sad": "Sadness",
}

_processor = None
_model = None


def _load():
    global _processor, _model
    if _model is None:
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        _processor = AutoImageProcessor.from_pretrained(MODEL_ID)
        _model = AutoModelForImageClassification.from_pretrained(MODEL_ID)
        _model.eval()

def _detect_and_crop_face(image_path: str):
    """Detects face using mediapipe, crops it, and calculates a quality score.
    Returns (cropped_pil_image, quality_score). If mediapipe fails or no face is found,
    it falls back to using the entire image with a low quality score."""
    import cv2
    image_cv = cv2.imread(image_path)
    if image_cv is None:
        return None, 0.0
        
    image_rgb = cv2.cvtColor(image_cv, cv2.COLOR_BGR2RGB)
    h, w, _ = image_rgb.shape
    fallback_image = Image.fromarray(image_rgb)
    
    try:
        from mediapipe.python.solutions import face_detection as mp_face_detection
        
        with mp_face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5) as face_detection:
            results = face_detection.process(image_rgb)
            
            if not results.detections:
                # No face detected, but return fallback so we have a prediction to fuse (at low weight)
                return fallback_image, 0.1
                
            # Get the highest confidence detection
            best_detection = max(results.detections, key=lambda d: d.score[0])
            bbox = best_detection.location_data.relative_bounding_box
            
            # Calculate quality score (confidence * size relative to frame)
            face_area = bbox.width * bbox.height
            confidence = best_detection.score[0]
            quality_score = float(confidence * min(1.0, face_area * 5))
            quality_score = max(0.1, min(1.0, quality_score))
            
            # Crop
            xmin = max(0, int(bbox.xmin * w))
            ymin = max(0, int(bbox.ymin * h))
            width = int(bbox.width * w)
            height = int(bbox.height * h)
            
            xmax = min(w, xmin + width)
            ymax = min(h, ymin + height)
            
            cropped_cv = image_rgb[ymin:ymax, xmin:xmax]
            if cropped_cv.size == 0:
                return fallback_image, 0.1
                
            cropped_pil = Image.fromarray(cropped_cv)
            return cropped_pil, quality_score
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Mediapipe face detection failed (%s), falling back to full image", e)
        return fallback_image, 0.8


def predict(image_path: str) -> dict:
    """Runs the pretrained face emotion model on an image and returns
    {label, confidence, probs, quality_score} reduced to the shared 4-class taxonomy, 
    or None if no face is detected."""
    import torch

    _load()

    face_img, quality_score = _detect_and_crop_face(image_path)
    if face_img is None:
        return None

    inputs = _processor(images=face_img, return_tensors="pt")

    with torch.no_grad():
        logits = _model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]

    native_labels = _model.config.id2label
    reduced_probs = {}
    for idx, prob in enumerate(probs.tolist()):
        native_label = native_labels[idx].lower()
        mapped = LABEL_MAP.get(native_label)
        if mapped:
            reduced_probs[mapped] = reduced_probs.get(mapped, 0.0) + prob

    total = sum(reduced_probs.values())
    if total <= 0:
        return None
    reduced_probs = {k: v / total for k, v in reduced_probs.items()}

    top_label = max(reduced_probs, key=reduced_probs.get)
    return {
        "label": top_label, 
        "confidence": reduced_probs[top_label], 
        "probs": reduced_probs,
        "quality_score": quality_score
    }
