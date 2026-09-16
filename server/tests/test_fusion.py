import pytest
from app.fusion.fuse import fuse_emotions

def test_fuse_emotions_single_modality():
    voice_res = {
        "label": "Happiness",
        "confidence": 0.9,
        "probs": {"Anger": 0.05, "Happiness": 0.9, "Neutral": 0.05, "Sadness": 0.0},
        "quality_score": 0.8
    }
    result = fuse_emotions({"voice": voice_res})
    
    assert result["label"] == "Happiness"
    assert result["confidence"] == 0.9
    assert result["weights"]["voice"] == 1.0

def test_fuse_emotions_multiple_modalities():
    voice_res = {
        "label": "Happiness",
        "confidence": 0.6,
        "probs": {"Anger": 0.1, "Happiness": 0.6, "Neutral": 0.2, "Sadness": 0.1},
        "quality_score": 0.2 # low quality
    }
    face_res = {
        "label": "Sadness",
        "confidence": 0.8,
        "probs": {"Anger": 0.1, "Happiness": 0.1, "Neutral": 0.0, "Sadness": 0.8},
        "quality_score": 0.8 # high quality
    }
    
    result = fuse_emotions({"voice": voice_res, "face": face_res})
    
    assert result["weights"]["voice"] == 0.2
    assert result["weights"]["face"] == 0.8
    assert result["label"] == "Sadness"
    assert result["probs"]["Sadness"] == (0.1 * 0.2) + (0.8 * 0.8) # 0.02 + 0.64 = 0.66

def test_fuse_emotions_zero_quality():
    voice_res = {
        "label": "Happiness",
        "confidence": 0.6,
        "probs": {"Anger": 0.1, "Happiness": 0.6, "Neutral": 0.2, "Sadness": 0.1},
        "quality_score": 0.0
    }
    face_res = {
        "label": "Sadness",
        "confidence": 0.8,
        "probs": {"Anger": 0.1, "Happiness": 0.1, "Neutral": 0.0, "Sadness": 0.8},
        "quality_score": 0.0
    }
    
    result = fuse_emotions({"voice": voice_res, "face": face_res})
    assert result["weights"]["voice"] == 0.5
    assert result["weights"]["face"] == 0.5

def test_fuse_emotions_empty():
    result = fuse_emotions({})
    assert result["label"] == "Neutral"
    assert result["confidence"] == 0.0
    assert result["probs"]["Neutral"] == 1.0
