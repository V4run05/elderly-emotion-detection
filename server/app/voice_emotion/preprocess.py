import shutil
import subprocess
import tempfile
import os

import soundfile as sf
import numpy as np


def load_waveform(audio_path: str) -> np.ndarray:
    """Load an audio file as a 16kHz mono waveform for the emotion model's processor.

    librosa's current backend (libsndfile via `soundfile`) can't decode compressed formats
    like AAC/M4A (what the Android/Tizen clients record) on its own -- there's no bundled
    audioread/ffmpeg fallback anymore. So this always transcodes through ffmpeg to a 16kHz
    mono WAV first, then reads that directly. Requires `ffmpeg` to be on PATH.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg not found on PATH -- required to decode uploaded audio (e.g. AAC/M4A)"
        )

    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", audio_path,
                "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
            ],
            check=True,
            capture_output=True,
        )
        waveform, _ = sf.read(wav_path, dtype="float32")
        return waveform
    finally:
        os.remove(wav_path)
