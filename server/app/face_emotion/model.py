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


def predict(image_path: str) -> dict:
    """Runs the pretrained face emotion model on an image and returns
    {label, confidence, probs} reduced to the shared 4-class taxonomy, or None if no
    overlapping class had any probability mass (shouldn't normally happen)."""
    import torch

    _load()

    image = Image.open(image_path).convert("RGB")
    inputs = _processor(images=image, return_tensors="pt")

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
    return {"label": top_label, "confidence": reduced_probs[top_label], "probs": reduced_probs}
