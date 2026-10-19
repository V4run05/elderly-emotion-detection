"""Loads and runs the trained RandomForest model for physiological emotion recognition.

Expects a JSON payload containing simulated Wokwi sensors: HR (MAX30102), SpO2, GSR, Accel.
Outputs a prediction mapped to the 4-class taxonomy, along with a quality score.
"""

import os
import joblib
import numpy as np
from scipy.signal import find_peaks

_model = None
MODEL_PATH = os.path.join(os.path.dirname(__file__), "rf_model.pkl")

# Must match TARGET_SR in scripts/train_wesad.py -- the BVP peak-finding below assumes the
# incoming bvp array is sampled at this rate, since live payloads don't carry their own
# sample rate.
TARGET_SR = 32

# If the model uses the 4 classes: Anger, Happiness, Neutral, Sadness
CLASSES = ["Anger", "Happiness", "Neutral", "Sadness"]

def _load():
    global _model
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)

def extract_features(sensor_data):
    """
    sensor_data: dict with arrays for 'acc_x', 'acc_y', 'acc_z', 'bvp', 'gsr'.
    Must match scripts/train_wesad.py's extract_features(): [hr_bpm, acc_mag], where hr_bpm is
    estimated by counting BVP peaks and acc_mag is the mean 3-axis accelerometer magnitude.
    """
    acc_x = np.array(sensor_data.get('acc_x', [0.0]))
    acc_y = np.array(sensor_data.get('acc_y', [0.0]))
    acc_z = np.array(sensor_data.get('acc_z', [0.0]))
    acc_mag = float(np.mean(np.sqrt(acc_x**2 + acc_y**2 + acc_z**2)))

    bvp = np.array(sensor_data.get('bvp', [0.0]))
    if len(bvp) < 2:
        hr_bpm = 70.0
    else:
        peaks, _ = find_peaks(bvp, distance=8)
        duration_sec = len(bvp) / TARGET_SR
        hr_bpm = len(peaks) * (60.0 / duration_sec)
        hr_bpm = min(200.0, max(40.0, hr_bpm))

    return np.array([[hr_bpm, acc_mag]])

def calculate_quality_score(sensor_data) -> float:
    """Calculate quality score based on signal stability.
    If GSR or BVP are extremely noisy or flatlining, quality drops.
    """
    gsr = np.array(sensor_data.get('gsr', []))
    bvp = np.array(sensor_data.get('bvp', []))
    
    if len(gsr) == 0 or len(bvp) == 0:
        return 0.0
        
    # Basic heuristic: if std is 0 (flatline), quality is 0
    gsr_std = np.std(gsr)
    bvp_std = np.std(bvp)
    
    if gsr_std == 0 and bvp_std == 0:
        return 0.0
        
    # If the variance is too high (simulating disconnection noise)
    if gsr_std > 10.0 or bvp_std > 100.0:
        return 0.2
        
    return 0.8 # Normal simulated data

def predict(sensor_data: dict) -> dict:
    """Run the RandomForest model on sensor data dict.
    Returns {label, confidence, probs, quality_score}.
    """
    _load()
    quality_score = calculate_quality_score(sensor_data)
    
    # If the model hasn't been trained yet or is missing, return a fallback
    if _model is None:
        return {
            "label": "Neutral",
            "confidence": 1.0,
            "probs": {"Anger": 0.0, "Happiness": 0.0, "Neutral": 1.0, "Sadness": 0.0},
            "quality_score": 0.0 # No quality if no model
        }
        
    features = extract_features(sensor_data)
    probs_array = _model.predict_proba(features)[0]
    
    # Map the model's classes to probs dict
    model_classes = _model.classes_
    probs = {c: 0.0 for c in CLASSES}
    
    for cls, prob in zip(model_classes, probs_array):
        if cls in probs:
            probs[cls] = prob
            
    # Normalize if not 1.0 (though predict_proba should sum to 1)
    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}
    else:
        probs = {"Anger": 0.0, "Happiness": 0.0, "Neutral": 1.0, "Sadness": 0.0}
        
    top_label = max(probs, key=probs.get)
    confidence = probs[top_label]
    
    return {
        "label": top_label,
        "confidence": confidence,
        "probs": probs,
        "quality_score": quality_score
    }
