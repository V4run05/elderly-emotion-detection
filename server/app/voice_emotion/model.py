"""
Loads and runs the pretrained voice emotion model.

Model: autrainer/msp-podcast-emo-class-big4-w2v2-l-emo (Hugging Face, audEERING/autrainer),
a wav2vec2 model fine-tuned on MSP-Podcast for 4-class emotion recognition
(Anger, Happiness, Neutral, Sadness). No training step — this only runs inference.

This checkpoint is published in the `autrainer` framework's own format (YAML configs + a
checkpoint under `_best/`), not a plain Hugging Face `transformers` checkpoint — there is no
documented `AutoModelForAudioClassification.from_pretrained(...)` path for it. The only
documented, supported way to run it is the `autrainer inference` CLI:

    autrainer inference hf:autrainer/msp-podcast-emo-class-big4-w2v2-l-emo <data-root> <output-root>

which reads every audio file in <data-root> and writes a `results.csv` (and `results.yaml`)
into <output-root>. `predict()` below wraps that CLI call for a single file so it can be
plugged into the FastAPI request path.

Verified standalone (2026-09-11) with a synthetic test clip. The actual `results.csv` schema is:
    filename,prediction,output,A,H,N,S
where A/H/N/S are per-class probabilities (single-letter codes, not full names) and
`prediction` holds the winning single-letter code.
"""

import csv
import glob
import os
import sys
import subprocess
import tempfile
import shutil
import numpy as np

MODEL_ID = "autrainer/msp-podcast-emo-class-big4-w2v2-l-emo"
CLASS_CODES = {"A": "Anger", "H": "Happiness", "N": "Neutral", "S": "Sadness"}


def _autrainer_cli() -> str:
    """Resolve the `autrainer` console-script path next to the running interpreter.

    The server process runs with sys.executable pointed at the venv's python.exe, but that
    venv's Scripts/ dir (where the autrainer.exe entry point lives) isn't necessarily on PATH
    inside the process, so a bare "autrainer" can fail with FileNotFoundError.
    """
    candidate = os.path.join(os.path.dirname(sys.executable), "autrainer.exe")
    if os.path.exists(candidate):
        return candidate
    candidate = os.path.join(os.path.dirname(sys.executable), "autrainer")
    if os.path.exists(candidate):
        return candidate
    found = shutil.which("autrainer")
    if found:
        return found
    raise RuntimeError("Could not locate the 'autrainer' CLI executable")


def _find_predictions_csv(output_root: str) -> str:
    csv_files = glob.glob(os.path.join(output_root, "**", "*.csv"), recursive=True)
    if not csv_files:
        raise RuntimeError(
            f"autrainer inference produced no CSV output under {output_root}"
        )
    for path in csv_files:
        if os.path.basename(path).lower() == "results.csv":
            return path
    return csv_files[0]


def _parse_row(row: dict, quality_score: float) -> dict:
    probs = {}
    for code, label in CLASS_CODES.items():
        if code in row:
            probs[label] = float(row[code])

    if not probs:
        raise RuntimeError(f"Could not find class probability columns (A/H/N/S) in row: {row}")

    top_code = row["prediction"].strip()
    top_label = CLASS_CODES.get(top_code, top_code)
    confidence = probs.get(top_label, max(probs.values()))

    return {"label": top_label, "confidence": confidence, "probs": probs, "quality_score": quality_score}

def _calculate_quality_score(waveform_array: np.ndarray) -> float:
    """Calculate a quality score based on the RMS energy of the waveform.
    This acts as a simple proxy for Voice Activity Detection/SNR."""
    if len(waveform_array) == 0:
        return 0.0
    rms = np.sqrt(np.mean(waveform_array**2))
    # Typical normalized audio RMS might be around 0.01 to 0.3
    # We want a smooth curve that reaches ~1.0 around 0.1 RMS
    # A simple squashing function or just clipping:
    score = min(1.0, rms * 10.0) 
    # Boost it slightly if there is at least some energy, but if it's dead silence it should be 0
    return max(0.0, float(score))

def predict(waveform_array, sample_rate: int = 16000) -> dict:
    """Run the pretrained emotion model on a single waveform and return
    {label, confidence, probs, quality_score}."""
    import soundfile as sf
    
    quality_score = _calculate_quality_score(waveform_array)

    work_dir = tempfile.mkdtemp(prefix="autrainer_")
    data_root = os.path.join(work_dir, "data")
    output_root = os.path.join(work_dir, "output")
    os.makedirs(data_root, exist_ok=True)

    audio_path = os.path.join(data_root, "clip.wav")
    sf.write(audio_path, waveform_array, sample_rate)

    try:
        subprocess.run(
            [_autrainer_cli(), "inference", f"hf:{MODEL_ID}", data_root, output_root],
            check=True,
            capture_output=True,
            text=True,
        )
        csv_path = _find_predictions_csv(output_root)
        with open(csv_path, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            raise RuntimeError(f"Predictions CSV {csv_path} was empty")
        return _parse_row(rows[0], quality_score)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
