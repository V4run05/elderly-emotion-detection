import pytest
import numpy as np
from app.physio_emotion.model import extract_features, calculate_quality_score, predict

def test_extract_features():
    sensor_data = {
        "acc_x": [1, 2, 3],
        "acc_y": [4, 5, 6],
        "acc_z": [7, 8, 9],
        "bvp": [10, 11, 12],
        "gsr": [0.1, 0.2, 0.3]
    }
    
    features = extract_features(sensor_data)
    assert features.shape == (1, 25)
    
    # Check acc_x features: mean=2, std=0.816, min=1, max=3, ptp=2
    assert np.isclose(features[0][0], 2.0)
    assert np.isclose(features[0][2], 1.0)
    assert np.isclose(features[0][3], 3.0)
    assert np.isclose(features[0][4], 2.0)

def test_calculate_quality_score_good():
    # Normal signal variance
    sensor_data = {
        "bvp": np.random.normal(0, 1, 100).tolist(),
        "gsr": np.random.normal(0, 0.1, 100).tolist()
    }
    score = calculate_quality_score(sensor_data)
    assert score == 0.8

def test_calculate_quality_score_flatline():
    # Zero variance (flatline)
    sensor_data = {
        "bvp": [10.0] * 100,
        "gsr": [0.5] * 100
    }
    score = calculate_quality_score(sensor_data)
    assert score == 0.0

def test_calculate_quality_score_noisy():
    # Extreme variance
    sensor_data = {
        "bvp": np.random.normal(0, 200, 100).tolist(),
        "gsr": np.random.normal(0, 20, 100).tolist()
    }
    score = calculate_quality_score(sensor_data)
    assert score == 0.2

def test_predict_no_model(monkeypatch):
    import app.physio_emotion.model
    # Ensure _model is None and prevent loading
    app.physio_emotion.model._model = None
    monkeypatch.setattr(app.physio_emotion.model, "_load", lambda: None)
    
    sensor_data = {
        "acc_x": [1, 2, 3],
        "acc_y": [4, 5, 6],
        "acc_z": [7, 8, 9],
        "bvp": [10, 11, 12],
        "gsr": [0.1, 0.2, 0.3]
    }
    
    result = predict(sensor_data)
    assert result["label"] == "Neutral"
    assert result["confidence"] == 1.0
    assert result["quality_score"] == 0.0
