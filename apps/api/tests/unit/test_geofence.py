"""Т35 (ADR-008): geofence детектор — чисти функции (haversine + преход
вътре→извън). Интеграцията е smoke през живия стек (endpoints + цикъл)."""

import math

from app.critical import detect_geofence, haversine_m


def test_haversine_known_distance():
    # София → Бургас ~ 245 km (грубо); tolerant
    d = haversine_m(42.6975, 23.3242, 42.5046, 27.4626)
    assert 300_000 < d < 380_000  # София→Бургас ~ 330-340 km права линия
    # нула разстояние
    assert haversine_m(42.7, 23.3, 42.7, 23.3) == 0


def _row(node: str, lat: float, lng: float) -> dict:
    return {"node": node, "ts": "2026-10-31T12:00:00+00:00", "lat": lat, "lng": lng}


ZONE = {"name": "релеи", "node": "*", "lat": 42.6975, "lng": 23.3242, "radius_m": 1000}


def test_left_zone_event():
    # последната позиция ИЗВЪН (в София-център + ~0.03° северно ≈ 3.3 km),
    # предходната ВЪТРЕ → event
    rows = [_row("!aaa", 42.7250, 23.3242), _row("!aaa", 42.6976, 23.3242)]
    out = detect_geofence(rows, [ZONE])
    assert len(out) == 1
    assert out[0].kind == "geofence"
    assert out[0].event_key == "geofence:релеи:!aaa"
    assert out[0].payload["node"] == "!aaa"
    assert out[0].payload["distance_m"] > 1000


def test_still_inside_no_event():
    rows = [_row("!aaa", 42.6976, 23.3242), _row("!aaa", 42.6977, 23.3242)]
    assert detect_geofence(rows, [ZONE]) == []


def test_never_inside_no_event():
    # и двете позиции извън зоната — няма преход, няма event
    rows = [_row("!aaa", 42.7250, 23.3242), _row("!aaa", 42.7300, 23.3242)]
    assert detect_geofence(rows, [ZONE]) == []


def test_zone_scope_filters_nodes():
    rows = [_row("!bbb", 42.7250, 23.3242), _row("!bbb", 42.6976, 23.3242)]
    zone = {**ZONE, "node": "!ccc"}
    assert detect_geofence(rows, [zone]) == []


def test_single_position_and_bad_zone_are_safe():
    # само една позиция → няма преход; боклучива зона → прескача
    rows = [_row("!aaa", 42.7250, 23.3242)]
    assert detect_geofence(rows, [ZONE]) == []
    bad = [{"name": "з", "node": "*", "lat": "не-число", "lng": 23.3, "radius_m": 100}]
    assert detect_geofence([_row("!aaa", 42.7, 23.3), _row("!aaa", 42.7, 23.3)], bad) == []
    assert detect_geofence([], [ZONE]) == []
