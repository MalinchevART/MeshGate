"""Управление на възли: заглушаване/блокиране/изтриване (по желание на собственика)."""
import asyncio
import json
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
    username = f"dv-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/broker/credentials",
                         json={"username": username, "topics": ["#"]})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    yield {"username": username, "password": data["password"]}
    rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
    for row in rows:
        if row["username"] == username:
            await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


async def _count_packets(admin, node: str) -> int:
    rows = (await admin.get(f"{API}/v1/packets", params={
        "node": node, "limit": 200})).json()["data"]
    return len(rows)


async def _wait_device(admin, node: str, timeout_s: float = 12.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for d in (await admin.get(f"{API}/v1/devices")).json()["data"]:
            if d["external_id"] == node:
                return d
        await asyncio.sleep(0.5)
    return None


async def test_mute_block_delete_device(admin, mqtt_all):
    node = f"!{uuid.uuid4().hex[:8]}"
    topic = f"msh/emul/2/e/DevAdmin/{node}"

    async def pub(text: str):
        await publish_mqtt(topic, json.dumps({
            "id": int(time.time() * 1000) % 0xFFFF, "to": -1,
            "from": 123456789, "sender": node, "channel": 0,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": text},
        }), mqtt_all["username"], mqtt_all["password"])

    await pub("първи")
    dev = await _wait_device(admin, node)
    assert dev, "възелът не се регистрира"
    dev_id = dev["id"]

    # заглушаване: пакетите спират да се записват
    assert (await admin.post(f"{API}/v1/devices/{dev_id}/mute")).status_code == 200
    await asyncio.sleep(0.5)
    before = await _count_packets(admin, node)
    for _ in range(3):
        await pub("шум")
    await asyncio.sleep(2.5)
    assert await _count_packets(admin, node) == before, "заглушеният възел пак пише"

    # филтърът по списъка показва заглушените
    muted_list = (await admin.get(f"{API}/v1/devices",
                                  params={"filter": "muted"})).json()["data"]
    assert any(d["id"] == dev_id and d["muted"] for d in muted_list)

    # възстановяване: пакетите се записват отново
    assert (await admin.post(f"{API}/v1/devices/{dev_id}/unmute")).status_code == 200
    await asyncio.sleep(0.5)
    await pub("отново на линия")
    await asyncio.sleep(2.0)
    assert await _count_packets(admin, node) == before + 1

    # блокиране = същото пропускане, но със защитен смисъл
    assert (await admin.post(f"{API}/v1/devices/{dev_id}/block")).status_code == 200
    await asyncio.sleep(0.5)
    before2 = await _count_packets(admin, node)
    await pub("блокиран")
    await asyncio.sleep(2.0)
    assert await _count_packets(admin, node) == before2

    # изтриване с пакети: възел + събития + пакети изчезват
    assert (await admin.delete(f"{API}/v1/devices/{dev_id}?packets=1")).status_code == 200
    await asyncio.sleep(0.5)
    devs = (await admin.get(f"{API}/v1/devices")).json()["data"]
    assert not any(d["id"] == dev_id for d in devs)
    assert await _count_packets(admin, node) == 0
