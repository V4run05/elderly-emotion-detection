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
from app.analysis import masking


def session_day(session: dict) -> date:
    return datetime.fromisoformat(session["started_at"]).date()


def daily_series(sessions: list, days: int, today: date,
                 low_threshold: float | None = None) -> list:
    """One entry per calendar day (oldest first), including days with no conversation.
    low_threshold: personal low line from analysis/baseline.py (fixed default if None)."""
    by_day: dict = {}
    for s in sessions:
        if s.get("verbal_valence") is None or s.get("nonverbal_valence") is None:
            continue  # session never got an analysed answer
        by_day.setdefault(session_day(s), []).append(s)

    series = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_sessions = by_day.get(day, [])
        if not day_sessions:
            series.append({"date": day.isoformat(), "checkins": 0, "verbal_valence": None,
                           "nonverbal_valence": None, "masking_score": None, "status": None,
                           "safety_flag": False})
            continue
        verbal = sum(s["verbal_valence"] for s in day_sessions) / len(day_sessions)
        nonverbal = sum(s["nonverbal_valence"] for s in day_sessions) / len(day_sessions)
        reassurance = any(s.get("reassurance") for s in day_sessions)
        result = masking.analyse(verbal, nonverbal, ["x"] if reassurance else [], low_threshold)
        series.append({
            "date": day.isoformat(),
            "checkins": len(day_sessions),
            "verbal_valence": round(verbal, 3),
            "nonverbal_valence": round(nonverbal, 3),
            "masking_score": round(result["masking_score"], 3),
            "status": result["status"],
            "safety_flag": any(s.get("safety_flag") for s in day_sessions),
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
