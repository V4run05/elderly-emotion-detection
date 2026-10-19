"""Turns individual conversations into a daily picture and a family alert level.

A single sad-sounding moment means little; a pattern over days does. Each day's sessions are
averaged and classified with the same masking rule used per answer (see masking.py). The
alert then looks at a rolling window of recent days.

Alert levels, most severe first:
    urgent - a conversation in the window tripped the safety screen (analysis/safety.py)
    alert  - low/masked on several days, with masking involved (or simply low on many days)
    watch  - a couple of concerning days, or no conversations for a while
    ok     - nothing concerning
    none   - no conversations recorded yet
"""

from datetime import date, datetime, timedelta

from app import config
from app.analysis import baseline, masking


def session_day(session: dict) -> date:
    return datetime.fromisoformat(session["started_at"]).date()


def _weighted(sessions: list, key: str) -> float | None:
    """Mean of a session value, weighted by how many spoken readings each session had."""
    pairs = [(s[key], s.get("readings") or 1) for s in sessions if s.get(key) is not None]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def daily_series(sessions: list, days: int, today: date,
                 low_threshold: float | None = None, base: dict | None = None) -> list:
    """One entry per calendar day (oldest first), including days with no conversation.
    base: from analysis/baseline.compute(); the day is judged against the person's normal per
    channel. Without it, low_threshold (or the fixed default) is used on the fused value.
    Typed-only days have no reading but still count for the safety flag."""
    by_day: dict = {}
    for s in sessions:
        if s.get("verbal_valence") is None and not s.get("safety_flag"):
            continue  # session never got an analysed answer
        by_day.setdefault(session_day(s), []).append(s)

    series = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        all_sessions = by_day.get(day, [])
        day_sessions = [s for s in all_sessions if s.get("nonverbal_valence") is not None
                        and s.get("verbal_valence") is not None]
        flagged = any(s.get("safety_flag") for s in all_sessions)
        if not day_sessions:
            series.append({"date": day.isoformat(), "checkins": 0, "verbal_valence": None,
                           "nonverbal_valence": None, "masking_score": None, "status": None,
                           "vs_normal": None, "readings": 0, "safety_flag": flagged})
            continue
        verbal = sum(s["verbal_valence"] for s in day_sessions) / len(day_sessions)
        nonverbal = _weighted(day_sessions, "nonverbal_valence")
        reassurance = any(s.get("reassurance") for s in day_sessions)
        if base is not None:
            j = baseline.judge(base, nonverbal, _weighted(day_sessions, "voice_valence"),
                               _weighted(day_sessions, "face_valence"))
            value, low, vs_normal = j["value"], j["low_threshold"], (j["value"] if j["relative"] else None)
        else:
            value, low, vs_normal = nonverbal, low_threshold, None
        result = masking.analyse(verbal, value, ["x"] if reassurance else [], low)
        series.append({
            "date": day.isoformat(),
            "checkins": len(day_sessions),
            "verbal_valence": round(verbal, 3),
            "nonverbal_valence": round(nonverbal, 3),
            "vs_normal": vs_normal,
            "readings": sum(s.get("readings") or 1 for s in day_sessions),
            "masking_score": round(result["masking_score"], 3),
            "status": result["status"],
            "safety_flag": flagged,
        })
    return series


def alert(series: list, today: date, last_checkin: date | None, name: str | None = None,
          pronouns: tuple = ("they", "them", "their", "they're")) -> dict:
    """Computes the family alert from the most recent ALERT_WINDOW_DAYS entries of `series`.
    pronouns: (subject, object, possessive, is-contraction), e.g. ("she", "her", "her", "she's")."""
    name = name or config.ELDER_NAME
    subj, obj, _poss, is_ = pronouns
    window = series[-config.ALERT_WINDOW_DAYS:]
    checked = [d for d in window if d["checkins"] > 0]
    masked = sum(1 for d in checked if d["status"] == "masked")
    concern = sum(1 for d in checked if d["status"] in ("masked", "low"))
    days_since = (today - last_checkin).days if last_checkin else None
    stats = {"window_days": len(window), "checkin_days": len(checked), "concern_days": concern,
             "masked_days": masked, "days_since_last_checkin": days_since}

    def result(level, message):
        return {"level": level, "message": message, **stats}

    if last_checkin is None:
        return result("none", f"No conversations with {name} yet.")
    if any(d["safety_flag"] for d in window):
        reflexive = {"she": "herself", "he": "himself"}.get(subj, "themselves")
        verb = "are" if subj == "they" else "is"
        return result("urgent", f"{name} said something in a recent conversation that may mean {subj} "
                                f"{verb} thinking about harming {reflexive}. Please contact {obj} now.")
    n = len(checked)
    if concern >= config.ALERT_CONCERN_DAYS and masked >= config.ALERT_MASKED_DAYS:
        return result("alert", f"{name} has been saying {is_} fine, but seemed low on "
                               f"{concern} of the last {n} days {subj} talked. Consider calling {obj}.")
    if concern >= config.ALERT_ANY_CONCERN_DAYS:
        return result("alert", f"{name} seemed low on {concern} of the last {n} days {subj} talked. "
                               f"Consider calling {obj}.")
    if days_since is not None and days_since >= config.MISSED_CHECKIN_DAYS:
        return result("watch", f"No conversations with {name} for {days_since} days.")
    if concern >= config.WATCH_CONCERN_DAYS:
        detail = f" (while saying {is_} fine)" if masked else ""
        return result("watch", f"{name} seemed low on {concern} of the last {n} days {subj} "
                               f"talked{detail}. Worth keeping an eye on.")
    return result("ok", f"Nothing concerning from {name} in the last {len(window)} days.")
