"""Фасетна филтрация: тип/канал/възел в Packet Explorer (docs/11 интуитивност)."""
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
    username = f"fc-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/broker/credentials",
                         json={"username": username, "topics": ["#"]})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    yield {"username": username, "password": data["password"]}
    rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
    for row in rows:
        if row["username"] == username:
            await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


async def test_facets_and_filters(admin, mqtt_all):
    ch1 = f"Fac{uuid.uuid4().hex[:6]}"
    ch2 = f"Fac{uuid.uuid4().hex[:6]}"
    node = f"!{uuid.uuid4().hex[:8]}"

    def env(portnum, extra=None):
        return json.dumps({
            "id": int(time.time() * 1000) % 0xFFFF, "to": -1,
            "from": 123456789, "sender": node, "channel": 0,
            "decoded": {"portnum": portnum, **(extra or {})},
        })

    await publish_mqtt(f"msh/emul/2/e/{ch1}/{node}", env("TEXT_MESSAGE_APP", {"text": "едно"}),
                       mqtt_all["username"], mqtt_all["password"])
    await publish_mqtt(f"msh/emul/2/e/{ch1}/{node}", env("TELEMETRY_APP",
                       {"telemetry": {"device_metrics": {"battery_level": 66}}}),
                       mqtt_all["username"], mqtt_all["password"])
    await publish_mqtt(f"msh/emul/2/e/{ch2}/{node}", env("TEXT_MESSAGE_APP", {"text": "две"}),
                       mqtt_all["username"], mqtt_all["password"])
    await asyncio.sleep(2.5)

    # фасетите броят каналите и типовете
    facets = (await admin.get(f"{API}/v1/packets/facets?hours=2")).json()["data"]
    chans = {c["channel"]: c for c in facets["channels"]}
    assert ch1 in chans and ch2 in chans, [c["channel"] for c in facets["channels"]][:8]
    assert chans[ch1]["count"] >= 2
    assert "meshtastic-telemetry" in chans[ch1]["types"]
    assert any(t["type"] == "meshtastic-text" for t in facets["types"]), facets["types"][:8]

    # филтър по канал
    rows = (await admin.get(f"{API}/v1/packets", params={
        "channel": ch1, "limit": 50})).json()["data"]
    assert rows and all(f"/2/e/{ch1}/" in p["topic"] for p in rows), rows[:3]
    assert all(p["channel"] == ch1 and p["node"] == node for p in rows)

    # филтър по възел
    rows = (await admin.get(f"{API}/v1/packets", params={
        "node": node, "limit": 50})).json()["data"]
    assert rows and all(p["topic"].endswith(node) for p in rows)

    # комбинация тип + канал
    rows = (await admin.get(f"{API}/v1/packets", params={
        "packet_type": "meshtastic-telemetry", "channel": ch1, "limit": 50})).json()["data"]
    assert rows and all(p["packet_type"] == "meshtastic-telemetry" for p in rows)
    assert all(f"/2/e/{ch1}/" in p["topic"] for p in rows)


async def test_map_nodes(admin, mqtt_all):
    """Карта на възлите: последна позиция по възел от position пакетите."""
    ch = f"Map{uuid.uuid4().hex[:6]}"
    n1, n2 = f"!{uuid.uuid4().hex[:8]}", f"!{uuid.uuid4().hex[:8]}"

    async def pos(node, lat_i, lng_i):
        await publish_mqtt(
            f"msh/emul/2/e/{ch}/{node}",
            json.dumps({
                "id": int(time.time() * 1000) % 0xFFFF, "to": -1,
                "from": 123456789, "sender": node, "channel": 0,
                "decoded": {"portnum": "POSITION_APP",
                            "position": {"latitude_i": lat_i, "longitude_i": lng_i}},
            }),
            mqtt_all["username"], mqtt_all["password"])

    await pos(n1, 426977000, 233219000)
    await pos(n2, 424100000, 231000000)
    # по-стара позиция на n2 — трябва да остане само новата
    await asyncio.sleep(1.0)
    await pos(n2, 428000000, 235000000)
    await asyncio.sleep(2.5)

    m = (await admin.get(f"{API}/v1/devices/map", params={
        "hours": 2})).json()["data"]
    found = {n["node"]: n for n in m["nodes"]}
    assert n1 in found and n2 in found, [n["node"] for n in m["nodes"]][:8]
    assert abs(found[n1]["lat"] - 42.6977) < 1e-4
    assert abs(found[n1]["lng"] - 23.3219) < 1e-4
    assert abs(found[n2]["lat"] - 42.8) < 1e-4, "по-старата позиция не се презаписа"
    assert found[n1]["channel"] == ch
    assert found[n1]["packets"] >= 1


async def test_topology_edges(admin, mqtt_all):
    """Топология: NeighborInfo пакетите стават ребра „кой кого чу"."""
    ch = f"Topo{uuid.uuid4().hex[:6]}"
    n1, n2 = f"!{uuid.uuid4().hex[:8]}", f"!{uuid.uuid4().hex[:8]}"
    id1, id2 = int(n1[1:], 16), int(n2[1:], 16)
    seq = iter(range(0x8000, 0xFFF0))

    def env(sender, from_id, portnum, extra=None):
        return json.dumps({
            "id": next(seq), "to": -1, "from": from_id,
            "sender": sender, "channel": 0,
            "decoded": {"portnum": portnum, **(extra or {})},
        })

    async def pub(node, from_id, portnum, extra=None):
        await publish_mqtt(f"msh/emul/2/e/{ch}/{node}",
                           env(node, from_id, portnum, extra),
                           mqtt_all["username"], mqtt_all["password"])

    # позиции за двата възла + всеки репортва другия като съсед
    await pub(n1, id1, "POSITION_APP",
              {"position": {"latitude_i": 426977000, "longitude_i": 233219000}})
    await pub(n2, id2, "POSITION_APP",
              {"position": {"latitude_i": 424100000, "longitude_i": 231000000}})
    await pub(n1, id1, "NEIGHBORINFO_APP",
              {"neighborinfo": {"node_id": id1,
                                "neighbors": [{"node_id": id2, "snr": -6.5}]}})
    await pub(n2, id2, "NEIGHBORINFO_APP",
              {"neighborinfo": {"node_id": id2,
                                "neighbors": [{"node_id": id1, "snr": -12.0}]}})
    await asyncio.sleep(2.5)

    topo = (await admin.get(f"{API}/v1/devices/topology",
                            params={"hours": 2})).json()["data"]
    edges = {(e["from"], e["to"]): e for e in topo["edges"]}
    assert (n1, n2) in edges and (n2, n1) in edges, topo["edges"][:5]
    assert edges[(n1, n2)]["snr_avg"] == -6.5
    assert edges[(n2, n1)]["snr_max"] == -12.0
    assert edges[(n1, n2)]["packets"] >= 1
    assert topo["nodes"] >= 2

    # детайлът на пакета носи човешка обобщена форма (mesh.neighbors)
    rows = (await admin.get(f"{API}/v1/packets", params={
        "packet_type": "meshtastic-neighbor", "channel": ch,
        "limit": 10})).json()["data"]
    assert rows, "няма neighbor пакети в списъка"
    det = (await admin.get(f"{API}/v1/packets/{rows[0]['id']}")).json()["data"]
    assert det["mesh"] and det["mesh"]["neighbors"], det.get("mesh")
    assert det["mesh"]["node_id"] in (n1, n2)
    assert all(nb["node"].startswith("!") for nb in det["mesh"]["neighbors"])


async def test_pulse_strips(admin, mqtt_all):
    """Пулс-ленти: часови кофи по клас чуване; ГЛАВЕН регистър в темата
    се нормализира; daily режим; SNR средна стойност на кофа."""
    raw = uuid.uuid4().hex[:8]
    node = f"!{raw}"  # темата ще е с ГЛАВНИ букви — SQL lower() ги мачва
    env = json.dumps({
        "id": int(time.time() * 1000) % 0xFFFF, "to": -1,
        "from": int(raw, 16), "sender": node, "channel": 0,
        "rx_snr": 8.5,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "пулс тест"},
    })
    await publish_mqtt(f"msh/emul/2/e/PulseCh/!{raw.upper()}", env,
                       mqtt_all["username"], mqtt_all["password"])
    await asyncio.sleep(2.5)

    d = (await admin.get(f"{API}/v1/devices/pulse", params={"hours": 2})).json()["data"]
    assert d["hours"] == 2 and d["daily"] is False
    found = next((n for n in d["nodes"] if n["node"] == node), None)
    assert found, "главни букви в темата не се нормализират в пулса"
    b = found["buckets"][-1]
    assert b["plain"] >= 1 and b["encrypted"] == 0
    assert found["last"]
    # кофите са в хронологичен ред (ORDER BY node, bucket — регресия на реда
    # би обърнала лентата в UI)
    ts = [bb["t"] for bb in found["buckets"]]
    assert ts == sorted(ts), ts
    # възелът е уникален за теста → едно event с rx_snr 8.5 → avg е точно 8.5
    assert any(bb.get("snr") == 8.5 for bb in found["buckets"]), \
        "SNR агрегацията от events не се вижда или не е на точната кофа"

    # дневен режим: 7 кофи, дата-ключ
    d7 = (await admin.get(f"{API}/v1/devices/pulse",
                          params={"hours": 168, "daily": 1})).json()["data"]
    assert d7["daily"] is True
    f7 = next((n for n in d7["nodes"] if n["node"] == node), None)
    assert f7 and f7["buckets"] and len(f7["buckets"]) <= 7
    assert all(bb["t"][11:13] == "00" for bb in f7["buckets"])  # цели дни UTC

    # невалиден прозорец се клампа от двете страни
    d2 = (await admin.get(f"{API}/v1/devices/pulse?hours=0")).json()["data"]
    assert d2["hours"] == 1
    d3 = (await admin.get(f"{API}/v1/devices/pulse?hours=99999")).json()["data"]
    assert d3["hours"] == 168
