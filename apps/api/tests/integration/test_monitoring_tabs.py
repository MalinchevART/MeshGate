"""Т28–Т30 интеграционни: Фунията (бройки срещу известен сценарий),
Водопад + Ефир-часовник (smoke — формата и честните празни състояния).
Пускат се ВЪТРЕ в api контейнера срещу живия стек (или с MESHGATE_API)."""

import asyncio
import time
import uuid

import httpx
import pytest

from conftest import ITEST as ADMIN, ensure_itest_admin
from test_checklist import API, login, publish_mqtt


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


@pytest.fixture
async def mqtt_all(admin):
    """Креденшъли за публикуване (създава/трие през API-то) — 1:1 с test_routing."""
    username = f"mt-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/broker/credentials",
                         json={"username": username, "topics": ["#"]})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    yield {"username": username, "password": data["password"]}
    rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
    for row in rows:
        if row["username"] == username:
            await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


async def test_funnel_counts_known_scenario(admin, mqtt_all):
    """Т30 QA: публикуваме 3 декодируеми пакета → Ефир и Декодируеми растат
    поне с 3; нивата под тях остават видими (вкл. нулите)."""
    zone = uuid.uuid4().hex[:6]
    r0 = await admin.get(f"{API}/v1/stats/funnel", params={"hours": 6})
    assert r0.status_code == 200, r0.text
    base = r0.json()["data"]

    for i in range(3):
        await publish_mqtt(f"mesh/{zone}/dev{i}/up", b'{"battery": 77}',
                           mqtt_all["username"], mqtt_all["password"])
    deadline = time.time() + 15.0
    grew = False
    while time.time() < deadline:
        r1 = await admin.get(f"{API}/v1/stats/funnel", params={"hours": 6})
        d = r1.json()["data"]
        if d["air"] >= base["air"] + 3 and d["decoded"] >= base["decoded"] + 3:
            grew = True
            break
        await asyncio.sleep(0.5)
    assert grew, f"фунията не отчете 3-та пакета: {base} -> {d}"

    # структурни инварианти: всички нива присъстват и са неотрицателни
    for k in ("air", "decoded", "captured", "delivered", "deadletter"):
        assert isinstance(d[k], int) and d[k] >= 0


async def test_waterfall_shape_and_honest_empty(admin):
    """Т28: формата е винаги пълна (grain + edges); на криптираната BG мрежа
    NeighborInfo не се декодира — празното състояние е ЧЕСТНО отговор, не
    грешка. Ако все пак има ребра — клетките носят t/n/snr полетата."""
    r = await admin.get(f"{API}/v1/devices/waterfall", params={"hours": 24})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["grain"] == "hour"
    for e in d["edges"][:5]:
        assert {"from", "to", "packets", "cells"} <= set(e)
        for c in e["cells"][:5]:
            assert {"t", "n", "snr"} <= set(c)


async def test_airclock_shape_and_verdict(admin):
    """Т29: 7×24 клетки + извод с действие; при <7 дни историята е маркирана."""
    r = await admin.get(f"{API}/v1/devices/air-clock", params={"hours": 168})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert {"cells", "days_covered", "verdict"} <= set(d)
    assert d["verdict"]["action"] in ("send_now", "better_later", "flat", "no_data")
    assert "text" in d["verdict"]
    for c in d["cells"][:5]:
        assert {"dow", "h", "med_snr", "n"} <= set(c)
    if d["days_covered"] < 7:
        assert "note" in d["verdict"]
