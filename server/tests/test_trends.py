from datetime import date, datetime, time, timedelta

from app.analysis import trends

TODAY = date(2026, 10, 19)


def session(days_ago: int, verbal: float, nonverbal: float, reassurance=True, safety=False):
    started = datetime.combine(TODAY - timedelta(days=days_ago), time(9, 0)).astimezone()
    return {"started_at": started.isoformat(), "verbal_valence": verbal,
            "nonverbal_valence": nonverbal, "reassurance": int(reassurance),
            "safety_flag": int(safety)}


def run(sessions):
    series = trends.daily_series(sessions, 14, TODAY)
    last = max((trends.session_day(s) for s in sessions), default=None)
    return series, trends.alert(series, TODAY, last)


def test_series_has_one_entry_per_day_with_gaps():
    series, _ = run([session(0, 0.5, 0.3), session(3, 0.5, 0.3)])
    assert len(series) == 14
    assert series[-1]["date"] == TODAY.isoformat() and series[-1]["checkins"] == 1
    assert series[-2]["checkins"] == 0 and series[-2]["status"] is None


def test_same_day_sessions_are_averaged():
    series, _ = run([session(0, 0.8, 0.2), session(0, 0.4, -0.2)])
    assert series[-1]["checkins"] == 2
    assert series[-1]["verbal_valence"] == 0.6
    assert series[-1]["nonverbal_valence"] == 0.0


def test_no_data():
    _, alert = run([])
    assert alert["level"] == "none"


def test_healthy_week_is_ok():
    _, alert = run([session(d, 0.7, 0.3) for d in range(7)])
    assert alert["level"] == "ok"


def test_masked_pattern_raises_alert():
    sessions = [session(d, 0.6, -0.7) for d in range(4)] + [session(d, 0.7, 0.3) for d in range(4, 7)]
    _, alert = run(sessions)
    assert alert["level"] == "alert"
    assert alert["masked_days"] == 4
    assert "saying they're fine" in alert["message"]


def test_two_concerning_days_is_watch():
    sessions = [session(0, 0.6, -0.7), session(1, -0.6, -0.4)] + [session(d, 0.7, 0.3) for d in range(2, 7)]
    _, alert = run(sessions)
    assert alert["level"] == "watch"


def test_missed_checkins_is_watch():
    _, alert = run([session(d, 0.7, 0.3) for d in range(3, 7)])
    assert alert["level"] == "watch"
    assert alert["days_since_last_checkin"] == 3


def test_safety_flag_is_urgent_regardless_of_mood():
    _, alert = run([session(0, 0.5, 0.3, safety=True)])
    assert alert["level"] == "urgent"
