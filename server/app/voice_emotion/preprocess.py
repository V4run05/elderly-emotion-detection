import shutil
import subprocess
import tempfile
import os

import soundfile as sf
import numpy as np


def load_waveform(audio_path: str) -> np.ndarray:
    """Load an audio file as a 16kHz mono waveform for the emotion model's processor."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            raise RuntimeError(
                "ffmpeg not found on PATH and imageio-ffmpeg not installed. Required to decode audio."
            )

    # Check if file is empty
    if os.path.getsize(audio_path) == 0:
        return np.zeros(16000, dtype="float32")

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
    except subprocess.CalledProcessError as e:
        import logging
        logging.getLogger(__name__).warning("ffmpeg failed (likely empty/corrupt webm), returning silence. Error: %s", e.stderr.decode(errors='replace'))
        return np.zeros(16000, dtype="float32")
    finally:
        os.remove(wav_path)
