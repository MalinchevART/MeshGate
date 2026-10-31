"""Т27–Т30 чисти функции: изводът на Ефир-часовника (Т29) и седмичната
норма в брифа. SQL частта се покрива от интеграционните (жив стек)."""

import datetime as _dt

from app.notify.engine import week_norm_note
from app.routes.devices import air_clock_verdict

NOW = _dt.datetime(2026, 10, 31, 14, 0, tzinfo=_dt.timezone.utc)  # събота 14:00


def _full_week(base: float, best_hour: int = 21, spread: float = 3.0) -> list:
    """Синтетична седмица: всеки (dow, час) с медиана; best_hour е най-силният."""
    cells = []
    for dow in range(1, 8):
        for h in range(24):
            med = base - spread + (spread * 2) * (1 if h == best_hour else 0.25)
            cells.append({"dow": dow, "h": h, "med_snr": round(med, 1), "n": 5})
    return cells


# ---------- Т29: изводът на часовника ----------------------------------------

def test_verdict_send_now_when_current_hour_is_best():
    cells = _full_week(-10.0, best_hour=NOW.hour)
    v = air_clock_verdict(cells, 14.0, now=NOW)
    assert v["action"] == "send_now"
    assert "Изпрати сега" in v["text"]


def test_verdict_better_later_points_to_best_upcoming_hour():
    cells = _full_week(-10.0, best_hour=21)  # 21:00 е най-силният час
    v = air_clock_verdict(cells, 14.0, now=NOW)
    assert v["action"] == "better_later"
    assert "21:00" in v["text"]


def test_verdict_no_data_and_flat():
    v = air_clock_verdict([], 0.0, now=NOW)
    assert v["action"] == "no_data"
    # равномерен ефир: всичко на едно ниво → няма ясно по-добър час
    cells = [{"dow": d, "h": h, "med_snr": -10.0, "n": 5}
             for d in range(1, 8) for h in range(24)]
    v2 = air_clock_verdict(cells, 14.0, now=NOW)
    assert v2["action"] == "flat"


def test_verdict_honest_below_seven_days():
    cells = _full_week(-10.0, best_hour=NOW.hour)
    v = air_clock_verdict(cells, 3.5, now=NOW)
    assert "3.5 дни" in v.get("note", "")
    v2 = air_clock_verdict(cells, 14.0, now=NOW)
    assert "note" not in v2


# ---------- Т29: седмичната норма в брифа ------------------------------------

def test_week_norm_none_when_no_data():
    assert week_norm_note(None, -8.0) is None
    assert week_norm_note(-8.0, None) is None


def test_week_norm_above_and_below():
    above = week_norm_note(-6.0, -9.5)
    assert above is not None and "над" in above and "+3.5 dB" in above
    below = week_norm_note(-12.0, -9.0)
    assert below is not None and "под" in below and "-3.0 dB" in below
