import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "mood_log.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emotion_label TEXT NOT NULL,
            confidence REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    return conn


def log_checkin(emotion_label: str, confidence: float, timestamp: str) -> None:
    conn = _get_connection()
    with conn:
        conn.execute(
            "INSERT INTO checkins (emotion_label, confidence, timestamp) VALUES (?, ?, ?)",
            (emotion_label, confidence, timestamp),
        )
    conn.close()


def get_recent(n: int = 5) -> list:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT emotion_label, confidence, timestamp FROM checkins ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [
        {"emotion_label": r[0], "confidence": r[1], "timestamp": r[2]} for r in rows
    ]
