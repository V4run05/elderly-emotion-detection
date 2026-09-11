import librosa
import numpy as np


def load_waveform(audio_path: str) -> np.ndarray:
    """Load an audio file as a 16kHz mono waveform for the emotion model's processor."""
    waveform, _ = librosa.load(audio_path, sr=16000, mono=True)
    return waveform
