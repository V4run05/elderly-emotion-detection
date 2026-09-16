import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "mood_log.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    
    # We will just drop and recreate the tables for the POC to ensure schema is correct
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emotion_label TEXT NOT NULL,
            confidence REAL NOT NULL,
            per_modality_breakdown TEXT,
            timestamp TEXT NOT NULL
        )
        """
    )
    
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trigger_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL, 
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    return conn


def log_checkin(emotion_label: str, confidence: float, per_modality_breakdown: dict, timestamp: str) -> None:
    conn = _get_connection()
    breakdown_json = json.dumps(per_modality_breakdown)
    with conn:
        conn.execute(
            "INSERT INTO checkins (emotion_label, confidence, per_modality_breakdown, timestamp) VALUES (?, ?, ?, ?)",
            (emotion_label, confidence, breakdown_json, timestamp),
        )
    conn.close()


def log_trigger_event(event_type: str, status: str, timestamp: str) -> None:
    """
    event_type: e.g., 'HR_SPIKE', 'FALL_DETECTED'
    status: e.g., 'PROMPT_USER', 'ESCALATED', 'RESOLVED'
    """
    conn = _get_connection()
    with conn:
        conn.execute(
            "INSERT INTO trigger_events (event_type, status, timestamp) VALUES (?, ?, ?)",
            (event_type, status, timestamp),
        )
    conn.close()


def get_recent(n: int = 5) -> list:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT emotion_label, confidence, per_modality_breakdown, timestamp FROM checkins ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    
    result = []
    for r in rows:
        try:
            breakdown = json.loads(r[2]) if r[2] else {}
        except:
            breakdown = {}
        result.append({"emotion_label": r[0], "confidence": r[1], "per_modality_breakdown": breakdown, "timestamp": r[3]})
    
    return result

def get_recent_triggers(n: int = 5) -> list:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT event_type, status, timestamp FROM trigger_events ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [{"event_type": r[0], "status": r[1], "timestamp": r[2]} for r in rows]
