"""Daily reminders (medications, routine tasks, appointments, calls).

A reminder has a time ("HH:MM" or none = any time today) and days: "daily", a weekday list
like "mon,wed,fri", or "once:YYYY-MM-DD". Each day it is one of:
    done   - confirmed in conversation (memory step) or ticked on the dashboard
    due    - its time has passed (or it has no time) and it isn't confirmed yet
    soon   - due within the next 60 minutes
    later  - later today
"""

from datetime import date, datetime, timedelta

from app.storage import db

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SOON = timedelta(minutes=60)


def scheduled_on(reminder: dict, day: date) -> bool:
    days = (reminder.get("days") or "daily").strip().lower()
    if days == "daily":
        return True
    if days.startswith("once:"):
        return days[5:] == day.isoformat()
    return WEEKDAYS[day.weekday()] in {d.strip()[:3] for d in days.split(",")}


def _at(day: date, hhmm: str | None) -> datetime | None:
    if not hhmm:
        return None
    try:
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)
    except ValueError:
        return None


def today(now: datetime) -> list:
    """Today's reminders with status, ordered by time."""
    day = now.date()
    log = db.reminder_log_for(day.isoformat())
    naive_now = now.replace(tzinfo=None)
    out = []
    for r in db.list_reminders():
        if not scheduled_on(r, day):
            continue
        when = _at(day, r["time"])
        if r["id"] in log and log[r["id"]]["status"] == "done":
            status = "done"
        elif when is None or when <= naive_now:
            status = "due"
        elif when - naive_now <= SOON:
            status = "soon"
        else:
            status = "later"
        out.append({**r, "status": status, "confirmed_by": log.get(r["id"], {}).get("source")})
    return out


def to_mention(now: datetime) -> dict | None:
    """The one reminder worth bringing up now: the most recently due unconfirmed one,
    else one coming up within the hour."""
    items = today(now)
    due = [r for r in items if r["status"] == "due"]
    if due:
        return sorted(due, key=lambda r: r["time"] or "00:00")[-1]
    soon = [r for r in items if r["status"] == "soon"]
    return soon[0] if soon else None


def next_later(now: datetime) -> dict | None:
    later = [r for r in today(now) if r["status"] in ("soon", "later")]
    return later[0] if later else None


def spoken_time(hhmm: str) -> str:
    """"17:30" -> "5:30 pm", "09:00" -> "9 am" (reads naturally when spoken by TTS)."""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return hhmm
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12} {suffix}" if m == 0 else f"{h12}:{m:02d} {suffix}"


def describe(r: dict) -> str:
    when = f" at {spoken_time(r['time'])}" if r.get("time") else ""
    notes = f" ({r['notes']})" if r.get("notes") else ""
    return f"{r['title']}{when}{notes}"
