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


def speech_span(waveform: np.ndarray, frame_s: float = 0.03) -> tuple[int, int] | None:
    """(first, last) sample of speech: frames clearly above the background noise. None if silent."""
    n = int(frame_s * SAMPLE_RATE)
    if len(waveform) < n:
        return None
    frames = waveform[: len(waveform) // n * n].reshape(-1, n)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    p95, floor = float(np.percentile(rms, 95)), float(np.percentile(rms, 10))
    threshold = max(0.005, 0.08 * p95)
    if floor < 0.5 * p95:            # there is a quieter background to compare against
        threshold = max(threshold, 2.5 * floor)
    loud = np.nonzero(rms > threshold)[0]
    if len(loud) == 0:
        return None
    return int(loud[0] * n), int((loud[-1] + 1) * n)


def speech_seconds(waveform: np.ndarray) -> float:
    """Length of the spoken part, from the first to the last speech frame. Recordings end with ~1.8 s
    of silence (end-of-answer detection), so the clip length is not the speech length."""
    span = speech_span(waveform)
    return (span[1] - span[0]) / SAMPLE_RATE if span else 0.0


def voice_quality(waveform: np.ndarray) -> float:
    """0..1 proxy for "was there usable speech": loudness (RMS), zero if the clip is too short."""
    if len(waveform) < config.MIN_SPEECH_SECONDS * SAMPLE_RATE:
        return 0.0
    rms = float(np.sqrt(np.mean(waveform ** 2)))
    return float(min(1.0, rms / config.VOICE_RMS_FULL_QUALITY))
