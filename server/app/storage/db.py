"""SQLite storage.

sessions      one conversation with the companion (open-ended), with its summary scores (recomputed
              after every turn) and a one-line summary + wellbeing signals from the memory step.
              `checkin` = 1 when the greeting asked the once-a-day "how are you feeling?" question.
turns         one message from the person (spoken or typed): transcript, reply, full analysis JSON.
              `context` = "wellbeing" for the answer to the daily question, else "chat".
profile       the single person's profile from the setup page (one JSON row).
reminders     routine tasks / medications / appointments (from setup, family, or the dashboard).
reminder_log  whether a reminder was done on a given day (confirmed in conversation or dashboard).
memories      things the companion has learned in conversation (people, events, preferences...).
onboarding    "get to know you" conversations that fill in the profile (not check-ins).

Raw audio/images are NOT stored (unless KEEP_MEDIA=true): only derived scores and text.
"""

import json
import sqlite3
from contextlib import contextmanager

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,          -- ISO 8601 with local UTC offset
    ended_at TEXT,
    greeting TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0, -- 1 = synthetic history from scripts/seed_demo.py
    turn_count INTEGER NOT NULL DEFAULT 0,
    verbal_valence REAL,
    nonverbal_valence REAL,
    masking_score REAL,
    status TEXT,                        -- ok | low | masked
    reassurance INTEGER NOT NULL DEFAULT 0,
    safety_flag INTEGER NOT NULL DEFAULT 0,
    summary TEXT,                       -- one line, written by the memory step after the session
    signals_json TEXT,                  -- wellbeing signals (sleep, appetite, pain, ...) from it
    checkin INTEGER NOT NULL DEFAULT 0, -- 1 = greeting asked the daily "how are you feeling?"
    voice_valence REAL,                 -- mean per channel over the spoken readings (personal baseline)
    face_valence REAL,
    readings INTEGER NOT NULL DEFAULT 0 -- spoken messages that gave a voice/face reading
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    transcript TEXT NOT NULL,
    reply_text TEXT NOT NULL,
    verbal_valence REAL NOT NULL,
    nonverbal_valence REAL NOT NULL,
    masking_score REAL NOT NULL,
    status TEXT NOT NULL,
    safety_flag INTEGER NOT NULL DEFAULT 0,
    analysis_json TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT 'chat',  -- wellbeing (answer to the daily question) | chat
    input TEXT NOT NULL DEFAULT 'voice'    -- voice | typed
);
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'task',     -- medication | task | appointment | call | other
    time TEXT,                             -- "HH:MM" or NULL (any time of day)
    days TEXT NOT NULL DEFAULT 'daily',    -- daily | "mon,wed,fri" | "once:YYYY-MM-DD"
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'family', -- setup | family | companion
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminder_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    date TEXT NOT NULL,                    -- YYYY-MM-DD
    status TEXT NOT NULL,                  -- done
    at TEXT NOT NULL,
    source TEXT NOT NULL,                  -- conversation | dashboard
    UNIQUE (reminder_id, date)
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,                    -- person | event | preference | health | fact
    text TEXT NOT NULL,
    person TEXT,
    event_date TEXT,                       -- YYYY-MM-DD for events
    session_id TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS onboarding (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    state_json TEXT NOT NULL               -- remaining topics + log of questions/answers/learned
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
"""

# Columns added after the first release; init() adds them to older databases.
MIGRATIONS = {
    "sessions": [("summary", "TEXT"), ("signals_json", "TEXT"), ("checkin", "INTEGER NOT NULL DEFAULT 0"),
                 ("voice_valence", "REAL"), ("face_valence", "REAL"), ("readings", "INTEGER NOT NULL DEFAULT 0")],
    "turns": [("context", "TEXT NOT NULL DEFAULT 'chat'"), ("input", "TEXT NOT NULL DEFAULT 'voice'")],
}


@contextmanager
def _conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, kind in cols:
                if name not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


# ---------------------------------------------------------------- sessions & turns
def create_session(session_id: str, started_at: str, greeting: str, is_demo: bool = False,
                   checkin: bool = False) -> None:
    with _conn() as c:
        c.execute("INSERT INTO sessions (id, started_at, greeting, is_demo, checkin) VALUES (?, ?, ?, ?, ?)",
                  (session_id, started_at, greeting, int(is_demo), int(checkin)))


def get_session(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session(row) if row else None


def _session(row) -> dict:
    s = dict(row)
    s["signals"] = json.loads(s.pop("signals_json") or "null")
    return s


def add_turn(session_id: str, turn_index: int, created_at: str, transcript: str,
             reply_text: str, analysis: dict, context: str = "chat", input_kind: str = "voice") -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO turns (session_id, turn_index, created_at, transcript, reply_text,
               verbal_valence, nonverbal_valence, masking_score, status, safety_flag,
               analysis_json, context, input) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, turn_index, created_at, transcript, reply_text,
             analysis["verbal"]["valence"], analysis["nonverbal"]["valence"],
             analysis["masking_score"], analysis["status"], int(analysis["safety_flag"]),
             json.dumps(analysis), context, input_kind),
        )


def flag_turn_safety(session_id: str, turn_index: int) -> None:
    """A late result from the self-harm screen: mark the message and its conversation."""
    with _conn() as c:
        c.execute("UPDATE turns SET safety_flag = 1 WHERE session_id = ? AND turn_index = ?", (session_id, turn_index))
        c.execute("UPDATE sessions SET safety_flag = 1 WHERE id = ?", (session_id,))


def wellbeing_answered_on(day: str) -> bool:
    """True if the daily "how are you feeling?" was answered on `day` (YYYY-MM-DD)."""
    with _conn() as c:
        row = c.execute("SELECT 1 FROM turns WHERE context = 'wellbeing' AND substr(created_at, 1, 10) = ? "
                        "LIMIT 1", (day,)).fetchone()
    return row is not None


def replies_on(day: str) -> list:
    """Everything the companion said on `day` (greetings + replies), oldest first."""
    with _conn() as c:
        greetings = [r[0] for r in c.execute(
            "SELECT greeting FROM sessions WHERE substr(started_at, 1, 10) = ? ORDER BY started_at", (day,))]
        replies = [r[0] for r in c.execute(
            "SELECT reply_text FROM turns WHERE substr(created_at, 1, 10) = ? ORDER BY created_at", (day,))]
    return greetings + replies


def open_sessions() -> list:
    """Real (non-demo) conversations that were never ended."""
    with _conn() as c:
        return [_session(r) for r in c.execute(
            "SELECT * FROM sessions WHERE ended_at IS NULL AND is_demo = 0").fetchall()]


def get_turns(session_id: str) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
                         (session_id,)).fetchall()
    turns = []
    for r in rows:
        t = dict(r)
        t["analysis"] = json.loads(t.pop("analysis_json"))
        turns.append(t)
    return turns


def update_session(session_id: str, **fields) -> None:
    allowed = {"ended_at", "turn_count", "verbal_valence", "nonverbal_valence", "masking_score",
               "status", "reassurance", "safety_flag", "summary", "signals", "voice_valence",
               "face_valence", "readings"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown session fields: {bad}")
    if "signals" in fields:
        fields["signals_json"] = json.dumps(fields.pop("signals"))
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE sessions SET {sets} WHERE id = ?", (*fields.values(), session_id))


def list_sessions(since: str | None = None, limit: int | None = None) -> list:
    """Sessions newest first, optionally only those started at/after `since` (ISO string)."""
    query, args = "SELECT * FROM sessions", []
    if since:
        query += " WHERE started_at >= ?"
        args.append(since)
    query += " ORDER BY started_at DESC"
    if limit:
        query += " LIMIT ?"
        args.append(limit)
    with _conn() as c:
        return [_session(r) for r in c.execute(query, args).fetchall()]


def delete_sessions(demo_only: bool = False) -> int:
    with _conn() as c:
        cur = c.execute("DELETE FROM sessions" + (" WHERE is_demo = 1" if demo_only else ""))
        c.execute("DELETE FROM memories" + (" WHERE is_demo = 1" if demo_only else ""))
        return cur.rowcount


# ---------------------------------------------------------------- profile
def get_profile() -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT data FROM profile WHERE id = 1").fetchone()
    return json.loads(row["data"]) if row else None


def save_profile(data: dict, updated_at: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO profile (id, data, updated_at) VALUES (1, ?, ?) "
                  "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                  (json.dumps(data), updated_at))


# ---------------------------------------------------------------- reminders
def list_reminders(active_only: bool = True) -> list:
    query = "SELECT * FROM reminders" + (" WHERE active = 1" if active_only else "")
    with _conn() as c:
        return [dict(r) for r in c.execute(query + " ORDER BY time IS NULL, time, id").fetchall()]


def add_reminder(title: str, kind: str, time: str | None, days: str, notes: str, source: str,
                 created_at: str) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO reminders (title, kind, time, days, notes, source, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (title, kind, time, days, notes, source, created_at))
        return cur.lastrowid


def delete_reminder(reminder_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))


def replace_reminders(source: str, items: list, created_at: str) -> None:
    """Replace all reminders that came from `source` (e.g. the setup page) with `items`."""
    with _conn() as c:
        c.execute("DELETE FROM reminders WHERE source = ?", (source,))
        for r in items:
            c.execute("INSERT INTO reminders (title, kind, time, days, notes, source, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (r["title"], r["kind"], r["time"], r["days"], r.get("notes", ""), source, created_at))


def log_reminder(reminder_id: int, date: str, status: str, at: str, source: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO reminder_log (reminder_id, date, status, at, source) VALUES (?, ?, ?, ?, ?) "
                  "ON CONFLICT(reminder_id, date) DO UPDATE SET status = excluded.status, "
                  "at = excluded.at, source = excluded.source",
                  (reminder_id, date, status, at, source))


def reminder_log_for(date: str) -> dict:
    with _conn() as c:
        rows = c.execute("SELECT reminder_id, status, source FROM reminder_log WHERE date = ?",
                         (date,)).fetchall()
    return {r["reminder_id"]: {"status": r["status"], "source": r["source"]} for r in rows}


# ---------------------------------------------------------------- memories
def add_memory(created_at: str, kind: str, text: str, person: str | None, event_date: str | None,
               session_id: str | None, is_demo: bool = False) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO memories (created_at, kind, text, person, event_date, session_id, is_demo) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (created_at, kind, text, person, event_date, session_id, int(is_demo)))
        return cur.lastrowid


def list_memories(limit: int | None = None) -> list:
    query = "SELECT * FROM memories ORDER BY created_at DESC, id DESC" + (" LIMIT ?" if limit else "")
    with _conn() as c:
        return [dict(r) for r in c.execute(query, (limit,) if limit else ()).fetchall()]


def delete_memory(memory_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM memories WHERE id = ?", (memory_id,))


# ---------------------------------------------------------------- onboarding
def create_onboarding(oid: str, started_at: str, state_json: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO onboarding (id, started_at, state_json) VALUES (?, ?, ?)", (oid, started_at, state_json))


def get_onboarding(oid: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM onboarding WHERE id = ?", (oid,)).fetchone()
    return dict(row) if row else None


def update_onboarding(oid: str, state_json: str, done: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE onboarding SET state_json = ?, done = ? WHERE id = ?", (state_json, int(done), oid))
