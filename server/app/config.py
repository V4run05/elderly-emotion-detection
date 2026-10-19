"""All settings and tunable thresholds live here, so behaviour can be adjusted in one place.

Values can be overridden through environment variables (see server/.env.example).
Thresholds marked "measured" were set from the evaluation on real data (docs/EVALUATION.md); the
rest are first-pass heuristics. Re-run server/evaluation/ before changing the measured ones.
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
# The fast model is only started if the primary hasn't answered after this long (it used to start
# at once, which doubled token use and ran out the free daily budget after ~80 replies).
LLM_HEDGE_DELAY_S = _float("LLM_HEDGE_DELAY_S", 1.5)
# Tried in order when the models above are rate-limited or failing (a separate Groq budget).
# qwen3.8-27b gave fluent replies in the conversation simulation (docs/EVALUATION.md §6).
LLM_BACKUP_MODELS = [m for m in os.environ.get("LLM_BACKUP_MODELS", "qwen/qwen3.8-27b").split(",") if m]
# Memory extraction runs in the background after a check-in, so the slower, more faithful
# model is fine (20b invented a relationship in testing; 120b didn't).
MEMORY_MODEL = os.environ.get("MEMORY_MODEL", "openai/gpt-oss-120b")
# "Get to know you" extraction from single answers: fast model, runs while the reply is generated.
ONBOARDING_MODEL = os.environ.get("ONBOARDING_MODEL", "openai/gpt-oss-20b")
# Self-harm screen (analysis/safety.py): keyword regex + this LLM on every message.
# Measured: 100% direct / 92% indirect statements, 0 false alarms (keywords alone: 75% / 8%).
SAFETY_SCREEN_ENABLED = os.environ.get("SAFETY_SCREEN_ENABLED", "true").lower() == "true"
SAFETY_SCREEN_MODEL = os.environ.get("SAFETY_SCREEN_MODEL", "openai/gpt-oss-safeguard-20b")
# Tried in order if the screen model is rate-limited (safeguard-20b allows only 2k tokens/minute).
SAFETY_SCREEN_FALLBACKS = [m for m in os.environ.get("SAFETY_SCREEN_FALLBACKS",
                                                     "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m]
SAFETY_SCREEN_WAIT_S = _float("SAFETY_SCREEN_WAIT_S", 4.0)  # extra wait after the reply is ready
# Said in the fixed safety reply. Default: India's national mental-health helpline (24x7, free).
HELPLINE_NAME = os.environ.get("HELPLINE_NAME", "Tele-MANAS")
HELPLINE_NUMBER = os.environ.get("HELPLINE_NUMBER", "14416")
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
# Used until the personal baseline is ready. Measured on CREMA-D: the voice model reads neutral speech
# at -0.34 on average, so the old -0.20 flagged 75% of calm "I'm fine" answers as masked (88% false
# family alerts). -0.55 flags 11% of calm and 52% of sad answers (7% false alerts, 62% of low weeks).
LOW_NONVERBAL_THRESHOLD = _float("LOW_NONVERBAL_THRESHOLD", -0.55)  # at/below = "seems low"
NEGATIVE_VERBAL_THRESHOLD = _float("NEGATIVE_VERBAL_THRESHOLD", -0.20)  # at/below = "says not OK"
MASKING_GAP_THRESHOLD = _float("MASKING_GAP_THRESHOLD", 0.50)  # verbal - nonverbal gap needed

# --- Personal baseline (analysis/baseline.py) -----------------------------------------------
BASELINE_ENABLED = os.environ.get("BASELINE_ENABLED", "true").lower() == "true"
# Measured (evaluation/channel_sim.py, real voices + older faces, camera on some days): voice decides,
# k=2.0, 7 calibration conversations -> 72% of low weeks caught, 8% false alerts at 3 answers/day
# (87% / 5% at 6). k=1.5 catches more (86%) but doubles false alerts (16%).
BASELINE_SESSIONS = _int("BASELINE_SESSIONS", 7)        # calibration conversations
BASELINE_MIN_DROP = _float("BASELINE_MIN_DROP", 0.12)   # minimum drop below normal to count as low
BASELINE_SPREAD_K = _float("BASELINE_SPREAD_K", 2.0)    # or this many spreads, whichever is larger
BASELINE_MAX_LOW_LINE = _float("BASELINE_MAX_LOW_LINE", 0.0)  # personal low line never above this
# How voice and face are judged against their own normals: voice (voice decides; face only when there
# is no voice reading) | any (whichever channel is furthest below its normal) | mean. Measured: averaging
# dilutes the voice drop when the face stays normal (masking): 20% caught; "any" gives 22-37% false alerts.
BASELINE_COMBINE = os.environ.get("BASELINE_COMBINE", "voice")

# --- Quality ---------------------------------------------------------------------------------
MIN_SPEECH_SECONDS = 0.5
# A spoken message counts as a voice/face reading only with at least this much speech: drops near-empty
# readings ("hmm"). Measured on whole CREMA-D clips (evaluation/voice_length.py): sad vs neutral AUC stays
# 0.75-0.79 from 0.6 s of speech up. A higher cut-off would mostly drop SAD answers (quiet speech is
# measured as shorter: 163 sad vs 11 neutral clips under 0.6 s), so keep it low.
MIN_READING_SECONDS = _float("MIN_READING_SECONDS", 0.4)
MIN_READING_WORDS = _int("MIN_READING_WORDS", 2)   # used when the speech length is unknown (older data)
VOICE_RMS_FULL_QUALITY = 0.05  # RMS at which voice quality reaches 1.0
MIN_FACE_FRACTION = 0.08  # face box must cover at least this much of the frame (width ratio)

# --- Family alerts (rolling window over days that had a check-in) -------------------------------
ALERT_WINDOW_DAYS = _int("ALERT_WINDOW_DAYS", 7)
ALERT_CONCERN_DAYS = _int("ALERT_CONCERN_DAYS", 3)  # low or masked days -> "alert" (with masking)
ALERT_MASKED_DAYS = _int("ALERT_MASKED_DAYS", 2)
ALERT_ANY_CONCERN_DAYS = _int("ALERT_ANY_CONCERN_DAYS", 4)  # low days alone -> "alert"
WATCH_CONCERN_DAYS = _int("WATCH_CONCERN_DAYS", 2)
MISSED_CHECKIN_DAYS = _int("MISSED_CHECKIN_DAYS", 2)  # no check-in for this many days -> "watch"
