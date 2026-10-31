"""Т7 unit тестове: детектори + преходи на състоянието (чисти функции)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.critical import (
    DEFAULTS,
    Detected,
    detect_battery,
    detect_deadletter,
    detect_silence,
    plan_transitions,
    thresholds,
)

NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)


# ---- thresholds -----------------------------------------------------------

def test_thresholds_defaults_and_merge():
    assert thresholds(None) == DEFAULTS
    assert thresholds({"battery_pct": 10})["battery_pct"] == 10
    assert thresholds({"battery_pct": 10})["deadletter_24h"] == DEFAULTS["deadletter_24h"]


def test_thresholds_garbage_falls_back():
    assert thresholds({"battery_pct": "десет"})["battery_pct"] == DEFAULTS["battery_pct"]
    assert thresholds({"battery_pct": -5})["battery_pct"] == DEFAULTS["battery_pct"]
    assert thresholds({"silence_hours": None})["silence_hours"] == DEFAULTS["silence_hours"]


# ---- детектор батерия -----------------------------------------------------

def test_battery_below_threshold_inclusive():
    rows = [{"node": "!a", "bat": 19}, {"node": "!b", "bat": 20}, {"node": "!c", "bat": 21}]
    keys = {d.event_key for d in detect_battery(rows, 20)}
    assert keys == {"battery:!a", "battery:!b"}  # прагът е включващ


def test_battery_bad_rows_skipped():
    rows = [{"node": "", "bat": 1}, {"node": "!x", "bat": None},
            {"node": "!y", "bat": "N/A"}, {"bat": 5}]
    assert detect_battery(rows, 20) == []


def test_battery_payload_has_links():
    out = detect_battery([{"node": "!n1", "bat": 5}], 20)
    assert out[0].payload["node"] == "!n1"
    assert out[0].payload["battery"] == 5.0
    assert out[0].payload["links"]


# ---- детектор мъртви букви ------------------------------------------------

def test_deadletter_threshold():
    rows = [{"rule": "r1", "cnt": 3}, {"rule": "r2", "cnt": 2}]
    keys = {d.event_key for d in detect_deadletter(rows, 3)}
    assert keys == {"deadletter:r1"}


def test_deadletter_empty_rule_skipped():
    assert detect_deadletter([{"rule": "", "cnt": 99}], 3) == []


# ---- детектор мълчание ----------------------------------------------------

def _node(last_h: float, first_h: float = 1000.0, muted=False, blocked=False):
    return {
        "node": "!n",
        "last_seen": NOW - timedelta(hours=last_h),
        "first_seen": NOW - timedelta(hours=first_h),
        "muted": muted,
        "blocked": blocked,
    }


def test_silence_over_threshold():
    out = detect_silence([_node(last_h=13)], 12, now=NOW)
    assert len(out) == 1 and out[0].kind == "silence"
    assert out[0].payload["silent_hours"] == 13.0


def test_silence_new_node_does_not_alarm():
    assert detect_silence([_node(last_h=13, first_h=5)], 12, now=NOW) == []


def test_silence_muted_blocked_skipped():
    assert detect_silence([_node(last_h=13, muted=True)], 12, now=NOW) == []
    assert detect_silence([_node(last_h=13, blocked=True)], 12, now=NOW) == []


def test_silence_recent_node_ok():
    assert detect_silence([_node(last_h=2)], 12, now=NOW) == []


# ---- преходи ---------------------------------------------------------------

def _existing(key="k", status="open", until=None):
    return {"event_key": key, "status": status, "silenced_until": until}


def test_transitions_new_condition_resolves_old():
    plan = plan_transitions([_existing("old")], {"new"}, NOW)
    assert plan["resolve"] == [{"event_key": "old"}]
    assert plan["upsert"] == []  # "new" още не е в таблицата — insert е в run_once


def test_transitions_resolved_returns_reopens():
    plan = plan_transitions([_existing("k", "resolved")], {"k"}, NOW)
    assert plan["upsert"] == [{"event_key": "k", "action": "reopen"}]
    assert plan["resolve"] == []


def test_transitions_silenced_still_valid_refreshes():
    until = NOW + timedelta(hours=2)
    plan = plan_transitions([_existing("k", "silenced", until)], {"k"}, NOW)
    assert plan["upsert"] == [{"event_key": "k", "action": "refresh"}]


def test_transitions_expired_silence_wakes():
    until = NOW - timedelta(minutes=1)
    plan = plan_transitions([_existing("k", "silenced", until)], {"k"}, NOW)
    assert plan["upsert"] == [{"event_key": "k", "action": "wake"}]


def test_transitions_open_refreshes_and_missing_resolves():
    plan = plan_transitions([_existing("a", "open"), _existing("b", "open")], {"a"}, NOW)
    assert plan["upsert"] == [{"event_key": "a", "action": "refresh"}]
    assert plan["resolve"] == [{"event_key": "b"}]


def test_transitions_acked_condition_gone_resolves():
    plan = plan_transitions([_existing("k", "acked")], set(), NOW)
    assert plan["resolve"] == [{"event_key": "k"}]

# ---- Т18 канаря ------------------------------------------------------------

from app.critical import canary_threshold_hours, detect_silence_canary


def test_canary_threshold_none_uses_base():
    assert canary_threshold_hours(None, 12) == 12
    assert canary_threshold_hours(0, 12) == 12


def test_canary_threshold_rhythm_wins():
    # p95 = 40 мин → 2.5× = 1.67 ч → базата 12 ч печели
    assert canary_threshold_hours(40 * 60, 12) == 12
    # p95 = 20 ч → 2.5× = 50 ч → ритъмът печели
    assert canary_threshold_hours(20 * 3600, 12) == 50


def test_canary_detector_rhythm_guards_early_alarm():
    node = {
        "node": "!n", "last_seen": NOW - timedelta(hours=13),
        "first_seen": NOW - timedelta(days=30), "muted": False, "blocked": False,
    }
    # без ритъм: 13 ч > 12 ч база → аларма
    assert len(detect_silence_canary([node], 12, {}, now=NOW)) == 1
    # с научен ритъм 20 ч (праг 50 ч): 13 ч мълчание е НОРМАЛНО → без аларма
    assert detect_silence_canary([node], 12, {"!n": 20 * 3600}, now=NOW) == []


def test_canary_detector_payload_has_rhythm():
    node = {
        "node": "!n", "last_seen": NOW - timedelta(hours=60),
        "first_seen": NOW - timedelta(days=30), "muted": False, "blocked": False,
    }
    out = detect_silence_canary([node], 12, {"!n": 20 * 3600}, now=NOW)
    assert out[0].payload["rhythm_p95_min"] == 1200.0  # p95 в секунди → минути
