"""Т35 (ADR-008) E2E: зона + две позиции на възел (вътре → извън) през MQTT
→ evaluator цикълът открива прехода → критично събитие kind=geofence.
Накрая зоната се трие и събитието се resolve-ва само (детекторът спира)."""

import asyncio
import time
import uuid

import httpx
import pytest

from conftest import ITEST as ADMIN, ensure_itest_admin
from test_checklist import API, login, publish_mqtt


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num: int, wire: int, payload: bytes) -> bytes:
    return _varint((num << 3) | wire) + payload


def _ld(num: int, data: bytes) -> bytes:
    return _field(num, 2, _varint(len(data)) + data)


def _vi(num: int, n: int) -> bytes:
    return _field(num, 0, _varint(n))


def _i32(num: int, n: int) -> bytes:
    return _field(num, 5, (n & 0xFFFFFFFF).to_bytes(4, "little"))


def _position_envelope(from_id: int, pkt_id: int, lat: float, lng: float) -> bytes:
    inner = _i32(1, int(lat * 1e7)) + _i32(2, int(lng * 1e7))
    data = _vi(1, 3) + _ld(2, inner)  # POSITION_APP
    packet = _vi(1, from_id) + _vi(2, 0xFFFFFFFF) + _ld(4, data) + _vi(6, pkt_id)
    return _ld(1, packet) + _ld(2, b"LongFast") + _ld(3, b"!testgate")


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


@pytest.fixture
async def mqtt_all(admin):
    username = f"gf-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/broker/credentials",
                         json={"username": username, "topics": ["#"]})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    yield {"username": username, "password": data["password"]}
    rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
    for row in rows:
        if row["username"] == username:
            await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


async def test_geofence_left_zone_e2e(admin, mqtt_all):
    from_id = int(uuid.uuid4().hex[:8], 16)
    node = f"!{from_id:08x}"
    zone_name = f"e2e-{uuid.uuid4().hex[:6]}"
    lat_in, lng_in = 42.6975, 23.3242
    lat_out = 42.7450  # ~5.3 km северно — извън 100 м радиус

    zones = [{"name": zone_name, "node": node, "lat": lat_in, "lng": lng_in,
              "radius_m": 100}]
    r = await admin.put(f"{API}/v1/system/geofence", json={"zones": zones})
    assert r.status_code == 200, r.text

    try:
        # 1) вътре в зоната
        await publish_mqtt(f"msh/e2e/2/e/LongFast/{node}",
                           _position_envelope(from_id, int(uuid.uuid4().hex[:8], 16), lat_in, lng_in),
                           mqtt_all["username"], mqtt_all["password"])
        await asyncio.sleep(2)
        # 2) ИЗВЪН зоната (преходът)
        await publish_mqtt(f"msh/e2e/2/e/LongFast/{node}",
                           _position_envelope(from_id, int(uuid.uuid4().hex[:8], 16), lat_out, lng_in),
                           mqtt_all["username"], mqtt_all["password"])

        # 3) evaluator цикъл (tick е кратък) — чакаме критичното събитие
        deadline = time.time() + 90.0
        event = None
        while time.time() < deadline and event is None:
            r = await admin.get(f"{API}/v1/critical-events",
                                params={"hours": 24, "limit": 100})
            # httpx връща СУРИЯ JSON: събитията са в data.events
            for e in ((r.json().get("data") or {}).get("events") or []):
                if e.get("kind") == "geofence" and node in e.get("event_key", ""):
                    event = e
                    break
            if event is None:
                await asyncio.sleep(3)
        assert event is not None, "geofence събитието не светна за 90 с"
        assert event["payload"]["zone"] == zone_name
        assert event["payload"]["distance_m"] > 100
        assert event["severity"] == "important"
    finally:
        await admin.put(f"{API}/v1/system/geofence", json={"zones": []})
