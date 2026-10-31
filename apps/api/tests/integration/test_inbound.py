"""R2: входящ мост — внася от външен брокер, разпознава се, рутира се, без цикли."""

import asyncio
import time
import uuid

import httpx
import pytest
from paho.mqtt.client import CallbackAPIVersion, MQTTv5
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties as PahoProps

from conftest import ITEST as ADMIN, ensure_itest_admin
from test_checklist import API, REMOTE_HOST, login


@pytest.fixture
async def admin():
    ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


async def _wait_packets(admin, substr, n=1, timeout_s=12.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = await admin.get(f"{API}/v1/packets", params={"topic": substr, "limit": 10})
        if len(r.json().get("data") or []) >= n:
            return r.json()["data"]
        await asyncio.sleep(0.5)
    return []


def _publish_remote(topic, payload, user_props=None):
    """Публикува директно във външния (тестов) брокер."""
    import paho.mqtt.client as mqtt
    import threading

    cli = mqtt.Client(CallbackAPIVersion.VERSION1, protocol=MQTTv5,
                      client_id=f"in-{uuid.uuid4().hex[:6]}")
    ev = threading.Event()
    cli.on_connect = lambda *a, **k: ev.set()
    cli.connect(REMOTE_HOST, 1883, keepalive=30)
    cli.loop_start()
    ev.wait(timeout=5)
    props = None
    if user_props:
        props = PahoProps(PacketTypes.PUBLISH)
        props.UserProperty = user_props
    cli.publish(topic, payload, qos=0, properties=props)
    time.sleep(0.3)
    cli.disconnect(); cli.loop_stop()


async def test_inbound_bridge_full_flow(admin):
    zone = uuid.uuid4().hex[:6]
    # 1) входящ мост: от remote-broker, теми msh/<zone>/... -> локално msh/<zone>/...
    r = await admin.post(f"{API}/v1/bridges", json={
        "name": f"inb-{zone}", "direction": "inbound", "remote_host": REMOTE_HOST,
        "allow_internal": True, "rate_limit_per_min": 1000,
        "topic_map": [{"from_prefix": f"msh/{zone}", "to_prefix": f"msh/{zone}"}],
        "rules": [],
    })
    assert r.status_code == 201, r.text
    bid = r.json()["data"]["id"]

    # включване без потвърждение се отказва (risky)
    r = await admin.post(f"{API}/v1/bridges/{bid}/enable")
    assert r.status_code == 409

    await admin.post(f"{API}/v1/bridges/{bid}/enable",
                     json={"confirm_risky": True})
    try:
        await asyncio.sleep(2)  # мостът се свързва

        # 2) правилото на системата: msh/<zone>/# -> local out2/<тема>
        r = await admin.post(f"{API}/v1/routing", json={"definition": {
            "name": f"in-route-{zone}",
            "source": {"topic_filter": f"msh/{zone}/#"},
            "conditions": {"topic": {"include": [f"msh/{zone}/#"], "exclude": []}},
            "destinations": [{"type": "mqtt", "target": "local",
                              "topic_template": f"out2/{zone}/{{topic}}", "qos": 0}],
        }})
        assert r.status_code == 201, r.text
        rid = r.json()["data"]["id"]
        await admin.post(f"{API}/v1/routing/{rid}/enable")

        # 3) публикуваме във ВЪНШНИЯ брокер -> локално запис + рутирано излизане
        _publish_remote(f"msh/{zone}/a", b'{"v":1}')
        got = await _wait_packets(admin, f"msh/{zone}/a")
        assert got, "входящото съобщение не достигна локалния брокер"
        assert any(
            p["topic"] == f"msh/{zone}/a" and p["origin"] == f"bridge:{bid}" for p in got
        ), got
        out = await _wait_packets(admin, f"out2/{zone}/msh/{zone}/a")
        assert out, "правилото не сработи върху входящото съобщение"

        # 4) ехо-защита: вече маркирано съобщение от същия мост не се вдига
        echo_topic = f"msh/{zone}/echo"
        _publish_remote(echo_topic, b'{"echo":1}', user_props=[("mg_origin", f"bridge:{bid}")])
        echo_pkts = await _wait_packets(admin, echo_topic, timeout_s=4)
        assert not echo_pkts, "ехо-съобщение беше прието (цикъл!)"

        # 5) дедупликация: същото съобщение втори път -> пак 1 запис (TTL 60s)
        dup_topic = f"msh/{zone}/dup"
        _publish_remote(dup_topic, b'{"dup":1}')
        await _wait_packets(admin, dup_topic)
        _publish_remote(dup_topic, b'{"dup":1}')
        await asyncio.sleep(3)
        r = await admin.get(f"{API}/v1/packets", params={"topic": dup_topic, "limit": 10})
        exact = [p for p in r.json()["data"] if p["topic"] == dup_topic]
        assert len(exact) == 1, r.json()["data"]  # изходът на правилото съдържа темата като подниз

        await admin.post(f"{API}/v1/routing/{rid}/disable")
        await admin.delete(f"{API}/v1/routing/{rid}")
    finally:
        await admin.post(f"{API}/v1/bridges/{bid}/disable")
        await admin.delete(f"{API}/v1/bridges/{bid}")


async def test_cross_bridge_dedup(admin):
    """Еднакъв пакет от ДВА входящи моста влиза веднъж (кръстосан дедуп)."""
    zone = uuid.uuid4().hex[:6]
    ids = []
    for i in range(2):
        r = await admin.post(f"{API}/v1/bridges", json={
            "name": f"xd-{zone}-{i}", "direction": "inbound", "remote_host": REMOTE_HOST,
            "allow_internal": True, "rate_limit_per_min": 1000,
            "topic_map": [{"from_prefix": f"msh/{zone}", "to_prefix": f"msh/{zone}"}],
            "rules": [],
        })
        assert r.status_code == 201, r.text
        bid = r.json()["data"]["id"]
        await admin.post(f"{API}/v1/bridges/{bid}/enable", json={"confirm_risky": True})
        ids.append(bid)
    try:
        await asyncio.sleep(2)
        topic = f"msh/{zone}/x"
        _publish_remote(topic, b'{"cross":1}')
        await asyncio.sleep(4)
        r = await admin.get(f"{API}/v1/packets", params={"topic": topic, "limit": 10})
        exact = [p for p in r.json()["data"] if p["topic"] == topic]
        assert len(exact) == 1, exact  # и от двата моста — но записан веднъж
    finally:
        for bid in ids:
            await admin.post(f"{API}/v1/bridges/{bid}/disable")
            await admin.delete(f"{API}/v1/bridges/{bid}")
