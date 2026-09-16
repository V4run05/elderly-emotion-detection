"""Quality-score-weighted multimodal fusion: w_i = quality_i / sum(quality_j) across available
modalities, then a weighted average of each modality's class-probability distribution.

Supports an arbitrary number of modalities (e.g., voice, face, physio).
"""

def fuse_emotions(modality_results: dict) -> dict:
    """
    modality_results: dict of modality_name -> {label, confidence, probs, quality_score}
    Returns {label, confidence, probs, weights, quality_scores} where weights records
    how much each available modality contributed based on its quality_score.
    """
    # Filter out None results
    valid_results = {name: res for name, res in modality_results.items() if res is not None}
    
    if not valid_results:
        # Fallback if somehow everything fails
        return {
            "label": "Neutral",
            "confidence": 0.0,
            "probs": {"Anger": 0.0, "Happiness": 0.0, "Neutral": 1.0, "Sadness": 0.0},
            "weights": {},
            "quality_scores": {}
        }

    total_quality = sum(res.get("quality_score", 0.0) for res in valid_results.values())
    
    weights = {}
    if total_quality <= 0:
        # Degenerate case: all models returned 0 quality, split evenly
        even_weight = 1.0 / len(valid_results)
        for name in valid_results:
            weights[name] = even_weight
    else:
        for name, res in valid_results.items():
            base_weight = res.get("quality_score", 0.0) / total_quality
            
            # SALIENCE BOOST:
            # "Neutral" is often a default/baseline state (especially for Physio).
            # If a modality strongly detects a real emotion (Anger, Sadness, Happiness),
            # we multiply its weight so it doesn't get washed out by a resting heart rate.
            if res["label"] != "Neutral" and res["confidence"] > 0.5:
                base_weight *= 2.5  # 2.5x boost for salient emotions
                
            weights[name] = base_weight

    # Re-normalize weights after salience boost
    weight_sum = sum(weights.values())
    if weight_sum > 0:
        weights = {k: v / weight_sum for k, v in weights.items()}

    all_labels = set()
    for res in valid_results.values():
        all_labels.update(res["probs"].keys())

    fused_probs = {}
    for label in all_labels:
        prob = 0.0
        for name, res in valid_results.items():
            prob += weights[name] * res["probs"].get(label, 0.0)
        fused_probs[label] = prob

    top_label = max(fused_probs, key=fused_probs.get) if fused_probs else "Neutral"
    confidence = fused_probs.get(top_label, 0.0)
    
    quality_scores = {name: res.get("quality_score", 0.0) for name, res in valid_results.items()}

    return {
        "label": top_label,
        "confidence": confidence,
        "probs": fused_probs,
        "weights": weights,
        "quality_scores": quality_scores
    }
