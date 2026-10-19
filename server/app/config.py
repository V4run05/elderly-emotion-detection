"""All settings and tunable thresholds live here, so behaviour can be adjusted in one place.

Values can be overridden through environment variables (see server/.env.example).
Thresholds are first-pass heuristics, not calibrated values -- see docs/PROJECT_SPEC.md
("Open questions") before treating any of them as validated.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent
load_dotenv(SERVER_DIR / ".env")


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


# --- Paths -----------------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", SERVER_DIR / "data"))
DB_PATH = DATA_DIR / "companion.db"
AUDIO_DIR = DATA_DIR / "audio"  # generated reply MP3s
CERT_DIR = DATA_DIR / "certs"  # self-signed HTTPS cert for phone access
WEB_CLIENT_DIR = REPO_DIR / "clients" / "web"

# --- People ----------------------------------------------------------------------------------
ELDER_NAME = os.environ.get("ELDER_NAME", "Lakshmi")
COMPANION_NAME = os.environ.get("COMPANION_NAME", "Asha")

# --- External services -----------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# Replies: ask both models at once; use the better one (120b) if it answers within
# LLM_PRIMARY_WAIT_S, otherwise the fast one (20b). In testing 120b gave better, more culturally
# fitting and less made-up replies, but sometimes took 7-10 s on Groq; 20b is ~1 s every time.
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
LLM_FAST_MODEL = os.environ.get("LLM_FAST_MODEL", "openai/gpt-oss-20b")
LLM_PRIMARY_WAIT_S = _float("LLM_PRIMARY_WAIT_S", 3.0)
# Memory extraction runs in the background after a check-in, so the slower, more faithful
# model is fine (20b invented a relationship in testing; 120b didn't).
MEMORY_MODEL = os.environ.get("MEMORY_MODEL", "openai/gpt-oss-120b")
# "Get to know you" extraction from single answers: fast model, runs while the reply is generated.
ONBOARDING_MODEL = os.environ.get("ONBOARDING_MODEL", "openai/gpt-oss-20b")
# whisper-large-v3 over -turbo: Groq lists 10.3% vs 12% WER, and on our noisy Indian-English
# test clips it scored 11.4% vs 15.7%. Accuracy matters more here than ~0.2 s of latency.
STT_MODEL = os.environ.get("STT_MODEL", "whisper-large-v3")

# Text-to-speech (see app/dialogue/tts.py): edge | orpheus | gtts
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "edge")
TTS_EDGE_VOICE = os.environ.get("TTS_EDGE_VOICE", "en-IN-NeerjaNeural")
TTS_EDGE_RATE = os.environ.get("TTS_EDGE_RATE", "+0%")  # e.g. "+10%" faster, "-10%" slower
TTS_ORPHEUS_VOICE = os.environ.get("TTS_ORPHEUS_VOICE", "hannah")  # autumn|diana|hannah|austin|daniel|troy
TTS_ACCENT = os.environ.get("TTS_ACCENT", "co.in")  # gTTS fallback accent: co.in, com, co.uk

# --- Local models ----------------------------------------------------------------------------
VOICE_MODEL_ID = "autrainer/msp-podcast-emo-class-big4-w2v2-l-emo"
FACE_MODEL_ID = "trpakov/vit-face-expression"
TEXT_MODEL_ID = "cardiffnlp/twitter-roberta-base-sentiment-latest"

# --- Conversations ---------------------------------------------------------------------------
MAX_TURNS_PER_SESSION = _int("MAX_TURNS_PER_SESSION", 0)  # 0 = open-ended conversation (no limit)
HISTORY_TURNS = _int("HISTORY_TURNS", 20)                  # recent exchanges kept in the LLM's context
MEMORY_EVERY_N_TURNS = _int("MEMORY_EVERY_N_TURNS", 4)     # run the memory step every N messages (and at the end)
KEEP_MEDIA = os.environ.get("KEEP_MEDIA", "false").lower() == "true"  # keep raw audio/images?

# --- Emotion -> valence ----------------------------------------------------------------------
# Every modality is reduced to the same 4 classes. Valence is the probability-weighted sum of
# these values, giving a score in [-1, 1]. Anger is negative but weighted below Sadness because
# low mood (sadness/flatness), not irritation, is what this project is trying to catch.
CLASSES = ["Anger", "Happiness", "Neutral", "Sadness"]
CLASS_VALENCE = {"Anger": -0.5, "Happiness": 1.0, "Neutral": 0.0, "Sadness": -1.0}

# --- Masking rule (applied identically to a turn, a session, and a day) ------------------------
SAYS_OK_THRESHOLD = _float("SAYS_OK_THRESHOLD", 0.10)  # verbal valence at/above = "says OK"
LOW_NONVERBAL_THRESHOLD = _float("LOW_NONVERBAL_THRESHOLD", -0.20)  # at/below = "seems low"
NEGATIVE_VERBAL_THRESHOLD = _float("NEGATIVE_VERBAL_THRESHOLD", -0.20)  # at/below = "says not OK"
MASKING_GAP_THRESHOLD = _float("MASKING_GAP_THRESHOLD", 0.50)  # verbal - nonverbal gap needed

# --- Personal baseline (analysis/baseline.py) -----------------------------------------------
BASELINE_ENABLED = os.environ.get("BASELINE_ENABLED", "true").lower() == "true"
BASELINE_SESSIONS = _int("BASELINE_SESSIONS", 5)        # calibration check-ins
BASELINE_MIN_DROP = _float("BASELINE_MIN_DROP", 0.12)   # minimum drop below normal to count as low
BASELINE_SPREAD_K = _float("BASELINE_SPREAD_K", 2.0)    # or this many spreads, whichever is larger
BASELINE_MAX_LOW_LINE = _float("BASELINE_MAX_LOW_LINE", 0.0)  # personal low line never above this

# --- Quality ---------------------------------------------------------------------------------
MIN_SPEECH_SECONDS = 0.5
VOICE_RMS_FULL_QUALITY = 0.05  # RMS at which voice quality reaches 1.0
MIN_FACE_FRACTION = 0.08  # face box must cover at least this much of the frame (width ratio)

# --- Family alerts (rolling window over days that had a check-in) -------------------------------
ALERT_WINDOW_DAYS = _int("ALERT_WINDOW_DAYS", 7)
ALERT_CONCERN_DAYS = _int("ALERT_CONCERN_DAYS", 3)  # low or masked days -> "alert" (with masking)
ALERT_MASKED_DAYS = _int("ALERT_MASKED_DAYS", 2)
ALERT_ANY_CONCERN_DAYS = _int("ALERT_ANY_CONCERN_DAYS", 4)  # low days alone -> "alert"
WATCH_CONCERN_DAYS = _int("WATCH_CONCERN_DAYS", 2)
MISSED_CHECKIN_DAYS = _int("MISSED_CHECKIN_DAYS", 2)  # no check-in for this many days -> "watch"
