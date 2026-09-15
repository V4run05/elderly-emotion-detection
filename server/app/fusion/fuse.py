"""Confidence-weighted multimodal fusion: w_i = conf_i / sum(conf_j) across available
modalities, then a weighted average of each modality's class-probability distribution.

This was part of the project's original plan (see docs/VOICE_LOOP_PLAN.md's deferred-work
section) for whenever a second modality became available -- it's reapplied here for face +
voice, both now obtainable from an Android phone (camera + mic) rather than the watch (mic
only). Falls back to voice-only when no face reading is available (no camera frame, no face
detected, or the face model came back empty), matching the original "face is optional" design.
"""


def fuse_emotions(voice_result: dict, face_result: dict = None) -> dict:
    """voice_result / face_result: {label, confidence, probs} as returned by the respective
    predict() functions. Returns {label, confidence, probs, weights} where weights records
    how much each available modality contributed, for transparency/debugging."""
    if face_result is None:
        return {**voice_result, "weights": {"voice": 1.0, "face": 0.0}}

    voice_conf = voice_result["confidence"]
    face_conf = face_result["confidence"]
    total_conf = voice_conf + face_conf
    if total_conf <= 0:
        # Degenerate case (both models somehow returned zero confidence) -- split evenly.
        w_voice = w_face = 0.5
    else:
        w_voice = voice_conf / total_conf
        w_face = face_conf / total_conf

    labels = set(voice_result["probs"]) | set(face_result["probs"])
    fused_probs = {
        label: w_voice * voice_result["probs"].get(label, 0.0)
        + w_face * face_result["probs"].get(label, 0.0)
        for label in labels
    }

    top_label = max(fused_probs, key=fused_probs.get)
    return {
        "label": top_label,
        "confidence": fused_probs[top_label],
        "probs": fused_probs,
        "weights": {"voice": w_voice, "face": w_face},
    }
