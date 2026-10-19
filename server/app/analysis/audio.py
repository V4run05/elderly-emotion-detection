"""Audio decoding and quality scoring.

ffmpeg is a required SYSTEM dependency (not pip-installable): browsers record WebM/Opus,
phones record AAC/M4A, and `soundfile` (libsndfile) can decode neither. Every upload is
transcoded to 16 kHz mono WAV with ffmpeg before anything else reads it.
"""

import os
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf

from app import config

SAMPLE_RATE = 16000


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it (Windows: winget install --id Gyan.FFmpeg -e) "
            "and restart the terminal."
        )
    return path


def load_waveform(audio_path: str) -> np.ndarray:
    """Decode any audio file to a 16 kHz mono float32 waveform. Raises on undecodable input."""
    if os.path.getsize(audio_path) == 0:
        raise ValueError("empty audio upload")
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        proc = subprocess.run(
            [_ffmpeg(), "-y", "-i", audio_path, "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "wav",
             wav_path],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise ValueError(f"ffmpeg could not decode audio: {proc.stderr.decode(errors='replace')[-300:]}")
        waveform, _ = sf.read(wav_path, dtype="float32")
        if waveform.ndim > 1:
            waveform = waveform.mean(axis=1)
        return waveform
    finally:
        os.remove(wav_path)


def voice_quality(waveform: np.ndarray) -> float:
    """0..1 proxy for "was there usable speech": loudness (RMS), zero if the clip is too short."""
    if len(waveform) < config.MIN_SPEECH_SECONDS * SAMPLE_RATE:
        return 0.0
    rms = float(np.sqrt(np.mean(waveform ** 2)))
    return float(min(1.0, rms / config.VOICE_RMS_FULL_QUALITY))
