import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "mood_log.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    return conn


def add_turn(role: str, content: str, timestamp: str) -> None:
    conn = _get_connection()
    with conn:
        conn.execute(
            "INSERT INTO conversation_turns (role, content, timestamp) VALUES (?, ?, ?)",
            (role, content, timestamp),
        )
    conn.close()


def get_recent_turns(n: int = 10) -> list:
    """Returns up to the last n turns, oldest first, as [{role, content}, ...]."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT role, content FROM conversation_turns ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def reset_conversation() -> None:
    conn = _get_connection()
    with conn:
        conn.execute("DELETE FROM conversation_turns")
    conn.close()
