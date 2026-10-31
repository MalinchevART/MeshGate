"""Интеграционни тестове — приемъчният checklist (docs/04-mvp-scope.md).
Пускат се ВЪТРЕ в api контейнера срещу живия стек:
    docker compose exec api python -m pytest tests/integration -v
Изисква: стекът е вдигнат + remote-broker профилът (docker compose --profile test up -d).
"""

import asyncio
import json
import os
import time
import uuid

import httpx
import pytest
from paho.mqtt.client import MQTTv5
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties as PahoProps

# по подразбиране — ВЪТРЕ в api контейнера (exec); отвън: MESHGATE_API=http://api:8000
API = os.environ.get("MESHGATE_API", "http://127.0.0.1:8000")
EMQX_HOST = os.environ.get("EMQX_HOST", "emqx")
REMOTE_HOST = os.environ.get("REMOTE_BROKER_HOST", "remote-broker")

from conftest import ITEST

ADMIN = ITEST  # тестовете имат собствен потребител — не зависят от паролата на собственика


async def login(client: httpx.AsyncClient, creds: dict) -> str:
    r = await client.post(f"{API}/v1/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return r.cookies.get("mg_session")


@pytest.fixture
async def admin():
    from conftest import ensure_itest_admin

    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


@pytest.fixture
async def mqtt_credentials(admin):
    """Създава per-device MQTT креденшъли през API-то (админ); чисти след себе си."""
    created: list[str] = []

    async def make(topics: list[str]) -> dict:
        username = f"dev-{uuid.uuid4().hex[:8]}"
        r = await admin.post(f"{API}/v1/broker/credentials",
                             json={"username": username, "topics": topics})
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        created.append(username)
        return data

    yield make
    for username in created:
        rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
        for row in rows:
            if row["username"] == username:
                await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


def _publish_sync(topic, payload, username, password, user_props=None):
    import paho.mqtt.client as mqtt

    result = {"connected": False, "error": None}
    try:
        cli = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            protocol=MQTTv5,
            client_id=f"t-{uuid.uuid4().hex[:8]}",
        )
        cli.username_pw_set(username, password)
        import threading
        ev = threading.Event()

        def on_connect(c, userdata, flags, rc, properties=None):
            # MQTTv5 връща ReasonCode обект; 3.1.1 — int
            if getattr(rc, "value", rc) == 0:
                result["connected"] = True
            ev.set()

        cli.on_connect = on_connect
        cli.connect(EMQX_HOST, 1883, keepalive=30)
        cli.loop_start()
        ev.wait(timeout=5)
        if result["connected"]:
            p = None
            if user_props:
                p = PahoProps(PacketTypes.PUBLISH)
                p.UserProperty = user_props
            cli.publish(topic, payload, qos=0, properties=p)
            time.sleep(0.3)
        cli.disconnect()
        cli.loop_stop()
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


async def publish_mqtt(topic, payload, username, password, user_props=None):
    return await asyncio.to_thread(
        _publish_sync, topic, payload, username, password, user_props
    )


# ---------- потребители и пароли (меню/инсталатор ползват това) ----------

async def test_users_and_passwords(admin):
    u = f"op-{uuid.uuid4().hex[:8]}"
    old_pass = "operator-pass-1"
    new_pass = "changed-pass-9"
    reset_pass = "reset-pass-77"
    r = await admin.post(f"{API}/v1/users",
                         json={"username": u, "password": old_pass, "role": "operator"})
    assert r.status_code == 201, r.text
    uid = r.json()["data"]["id"]

    async with httpx.AsyncClient() as c:
        await login(c, {"username": u, "password": old_pass})

        # грешна текуща парола -> отказ
        r = await c.post(f"{API}/v1/auth/change-password",
                         json={"old_password": "грешна", "new_password": new_pass})
        assert r.status_code == 403

        # вярна смяна -> новата важи, старата не
        r = await c.post(f"{API}/v1/auth/change-password",
                         json={"old_password": old_pass, "new_password": new_pass})
        assert r.status_code == 200, r.text
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API}/v1/auth/login",
                         json={"username": u, "password": old_pass})
        assert r.status_code == 401
        r = await c.post(f"{API}/v1/auth/login",
                         json={"username": u, "password": new_pass})
        assert r.status_code == 200

    # admin рестет -> новата парола важи
    r = await admin.post(f"{API}/v1/users/{uid}/password",
                         json={"new_password": reset_pass})
    assert r.status_code == 200, r.text
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API}/v1/auth/login",
                         json={"username": u, "password": reset_pass})
        assert r.status_code == 200

    # изтриване на потребител
    r = await admin.delete(f"{API}/v1/users/{uid}")
    assert r.status_code == 200

    # последният администратор не може да бъде изтрит
    me = (await admin.get(f"{API}/v1/auth/me")).json()["data"]
    admins = [x for x in (await admin.get(f"{API}/v1/users")).json()["data"]
              if x["role"] == "admin"]
    if len(admins) == 1:
        r = await admin.delete(f"{API}/v1/users/{me['id']}")
        assert r.status_code == 409


# ---------- начална парола + профили (Фаза 1) ----------

async def test_default_password_flag_and_login():
    """login/me винаги връщат default_password — UI показва банер докато
    администраторът ползва началната парола."""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API}/v1/auth/login", json=ADMIN)
        assert r.status_code == 200
        assert "default_password" in r.json()["data"]
        assert isinstance(r.json()["data"]["default_password"], bool)
        cookie = r.cookies.get("mg_session")
        r = await c.get(f"{API}/v1/auth/me",
                        cookies={"mg_session": cookie})
        assert r.status_code == 200
        assert "default_password" in r.json()["data"]


async def get_setting(key):
    """Пряко от базата (тестът върви в api контейнера)."""
    import asyncpg
    import json as _json
    import os

    conn = await asyncpg.connect(
        host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        database=os.environ["PGDATABASE"],
    )
    try:
        v = await conn.fetchval("SELECT value FROM settings WHERE key = $1", key)
        return _json.loads(v) if v is not None else None
    finally:
        await conn.close()


async def test_profiles_apply_requires_confirmation(admin):
    # 1) рисков профил без потвърждение -> НИЩО не се прилага
    r = await admin.post(f"{API}/v1/profiles/controlled-public-bridge/apply",
                         json={"version": 1, "confirm_risky": False})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["applied"] is False and d["requires_confirmation"] is True
    assert await get_setting("bridge_outbound_enabled") is not True, \
        "изходящите мостове се включиха БЕЗ потвърждение!"

    # 2) с потвърждение -> прилага се
    r = await admin.post(f"{API}/v1/profiles/controlled-public-bridge/apply",
                         json={"version": 1, "confirm_risky": True})
    assert r.status_code == 200
    assert "controlled-public-bridge" in str(r.json()["data"]["applied"])
    assert await get_setting("bridge_outbound_enabled") is True

    # 3) "връщане назад" чрез прилагане на безопасен профил
    r = await admin.post(f"{API}/v1/profiles/home-gateway/apply",
                         json={"version": 1, "confirm_risky": False})
    assert r.status_code == 200
    assert await get_setting("bridge_outbound_enabled") is False

    audit = (await admin.get(f"{API}/v1/audit",
                             params={"action": "profile.apply"})).json()["data"]
    assert len(audit) >= 2


# ---------- §2: MQTT клиент се свързва и публикува ----------

async def test_02_client_connects_and_publishes(mqtt_credentials):
    cred = await mqtt_credentials(["mesh/+/up"])
    res = await publish_mqtt("mesh/dev1/up", b'{"temp": 21.5}',
                             cred["username"], cred["password"])
    assert res["connected"], res


# ---------- §3: пакетът се появява live (WebSocket) без презареждане ----------

async def test_03_packet_appears_live(mqtt_credentials):
    import websockets

    async with httpx.AsyncClient() as c:
        cookie = await login(c, ADMIN)
    cred = await mqtt_credentials(["mesh/+/up"])
    topic = f"mesh/{uuid.uuid4().hex[:6]}/up"
    marker = uuid.uuid4().hex

    async with websockets.connect(
        f"ws://127.0.0.1:8000/v1/packets/ws",
        additional_headers={"Cookie": f"mg_session={cookie}"},
    ) as ws:
        await publish_mqtt(topic, json.dumps({"marker": marker}).encode(),
                           cred["username"], cred["password"])
        deadline = time.time() + 10
        seen = False
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
            except asyncio.TimeoutError:
                break
            event = json.loads(raw)
            if event.get("type") == "packet" and event["data"]["topic"] == topic:
                seen = True
                break
        assert seen, "пакетът не пристигна през WebSocket"


# ---------- §5: UI данните показват реалния статус на брокера ----------

async def test_05_broker_status_is_real(admin, mqtt_credentials):
    r = await admin.get(f"{API}/v1/broker/status")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["connections"] >= 1  # поне ingest клиентът
    clients = (await admin.get(f"{API}/v1/broker/clients")).json()["data"]
    assert any(c["client_id"] == "meshgate-ingest" for c in clients)


# ---------- §6: конфигурацията се валидира и отразява в audit log ----------

async def test_06_config_validation_and_audit(admin):
    r = await admin.post(f"{API}/v1/bridges",
                         json={"name": "x!", "remote_host": "example.net",
                               "remote_port": 1883, "rules": []})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"

    name = f"audit-{uuid.uuid4().hex[:6]}"
    r = await admin.post(f"{API}/v1/bridges",
                         json={"name": name, "remote_host": "example.net",
                               "rules": [{"kind": "allow", "topic_pattern": "mesh/+/up"}]})
    assert r.status_code == 201, r.text
    bid = r.json()["data"]["id"]
    audit = (await admin.get(f"{API}/v1/audit", params={"action": "bridge.create"})).json()["data"]
    assert any(a["entity_id"] == name for a in audit)
    await admin.delete(f"{API}/v1/bridges/{bid}")


# ---------- §7: неоторизирани не могат да променят/публикуват ----------

async def test_7a_viewer_cannot_change_config(admin):
    vu = f"viewer-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/users",
                         json={"username": vu, "password": "viewer-pass-1", "role": "viewer"})
    assert r.status_code == 201, r.text
    async with httpx.AsyncClient() as c:
        await login(c, {"username": vu, "password": "viewer-pass-1"})
        r = await c.post(f"{API}/v1/bridges",
                         json={"name": "hack", "remote_host": "example.net", "rules": []})
        assert r.status_code == 403
        r = await c.post(f"{API}/v1/broker/test-publish", json={"topic": "t", "payload": "x"})
        assert r.status_code == 403
        r = await c.get(f"{API}/v1/packets")
        assert r.status_code == 200  # четене му е позволено


async def test_7b_anonymous_api_rejected():
    async with httpx.AsyncClient() as c:
        assert (await c.get(f"{API}/v1/packets")).status_code == 401
        assert (await c.post(f"{API}/v1/bridges", json={})).status_code == 401


async def test_7c_mqtt_wrong_password_rejected(mqtt_credentials):
    cred = await mqtt_credentials(["mesh/+/up"])
    res = await publish_mqtt("mesh/dev/up", b"x", cred["username"], "wrong-password")
    assert not res["connected"]


async def test_7d_mqtt_acl_denies_outside_topics(admin, mqtt_credentials):
    """Креденшъл с allow само на своя зона: subscription към чужда зона и
    publish към чужда тема не преминават (ефектът се проверява по данните)."""
    cred = await mqtt_credentials(["mesh/mine/up"])
    forbidden_topic = f"other/{uuid.uuid4().hex[:6]}/x"

    # 1) subscription извън ACL -> EMQX връща SUBACK с refusal reason code;
    #    paho ги вижда в on_subscribe (aiomqtt не хвърля там)
    suback = await asyncio.to_thread(_suback_sync, "other/#",
                                     cred["username"], cred["password"])
    assert any(code >= 0x80 for code in suback), f"очаквах отказ, получих {suback}"
    suback_ok = await asyncio.to_thread(_suback_sync, "mesh/mine/up",
                                        cred["username"], cred["password"])
    assert all(code < 0x80 for code in suback_ok), f"очаквах granted, получих {suback_ok}"

    # 2) publish извън ACL -> брокерът го изпуска; нищо не влиза в базата
    res = await publish_mqtt(forbidden_topic, b"should-not-pass",
                             cred["username"], cred["password"])
    assert res["connected"]
    await asyncio.sleep(1.5)
    rows = (await admin.get(f"{API}/v1/packets",
                            params={"topic": forbidden_topic})).json()["data"]
    assert rows == [], "забраненият publish не бива да се записва"


def _suback_sync(topic: str, username: str, password: str) -> list[int]:
    import threading

    import paho.mqtt.client as mqtt

    out = {"codes": None}
    ev = threading.Event()

    def on_connect(c, u, f, rc, properties=None):
        if getattr(rc, "value", rc) != 0:
            ev.set()

    def on_subscribe(c, u, mid, granted, properties=None):
        out["codes"] = [getattr(g, "value", g) for g in granted]
        ev.set()

    cli = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
        protocol=MQTTv5,
        client_id=f"sub-{uuid.uuid4().hex[:8]}",
    )
    cli.username_pw_set(username, password)
    cli.on_connect = on_connect
    cli.on_subscribe = on_subscribe
    cli.connect(EMQX_HOST, 1883, keepalive=30)
    cli.loop_start()
    try:
        cli.subscribe(topic, qos=0)
        ev.wait(timeout=5)
    finally:
        cli.disconnect()
        cli.loop_stop()
    return out["codes"] or [0x80]


# ---------- §8: неуспешен bridge не чупи локалния брокер ----------

async def test_08_failed_bridge_does_not_break_local(admin, mqtt_credentials):
    name = f"dead-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/bridges",
                         json={"name": name, "remote_host": "203.0.113.1",
                               "rules": [{"kind": "allow", "topic_pattern": "mesh/+"}]})
    assert r.status_code == 201, r.text
    bid = r.json()["data"]["id"]
    await admin.post(f"{API}/v1/bridges/{bid}/enable")
    # черна дупка: connect timeout 5s + retry — чакаме health да падне
    bridge_down = False
    for _ in range(8):
        await asyncio.sleep(2)
        health = (await admin.get(f"{API}/v1/system/health")).json()["data"]
        if health["components"]["bridge"] == "down":
            bridge_down = True
            break
    assert bridge_down, "bridge трябваше да отчете down за недостиж remote"
    assert health["components"]["broker"] == "ok"
    assert health["components"]["ingestion"] == "ok"

    cred = await mqtt_credentials(["mesh/+/up"])
    res = await publish_mqtt("mesh/local/up", "все още работи".encode(),
                             cred["username"], cred["password"])
    assert res["connected"] and res["error"] is None
    await admin.post(f"{API}/v1/bridges/{bid}/disable")
    await admin.delete(f"{API}/v1/bridges/{bid}")


# ---------- §10: bridge — забранени теми и цикли ----------

async def test_10_bridge_rules_and_loop_prevention(admin, mqtt_credentials):
    import aiomqtt

    name = f"br-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/bridges",
                         json={"name": name, "remote_host": REMOTE_HOST,
                               "allow_internal": True,
                               "topic_map": [{"from_prefix": "mesh", "to_prefix": "gw/mesh"}],
                               "rate_limit_per_min": 100,
                               "rules": [
                                   {"kind": "deny", "topic_pattern": "mesh/priv/#",
                                    "priority": 10, "reason": "лични съобщения"},
                                   {"kind": "allow", "topic_pattern": "mesh/+/up",
                                    "priority": 100},
                               ]})
    assert r.status_code == 201, r.text
    bid = r.json()["data"]["id"]

    t = (await admin.post(f"{API}/v1/bridges/{bid}/test",
                          json={"topic": "mesh/priv/x", "payload": "secret"})).json()["data"]
    assert t["action"] == "reject" and "лични" in t["reason"]
    t2 = (await admin.post(f"{API}/v1/bridges/{bid}/test",
                           json={"topic": "mesh/sens/up", "payload": "ok"})).json()["data"]
    assert t2["action"] == "forward"

    await admin.post(f"{API}/v1/bridges/{bid}/enable")
    await asyncio.sleep(2)  # engine-ът се свързва към remote

    # устройството може да публикува и в "частната" зона — решението дали тя
    # напуска системата е на BRIDGE правилата, не на устройството
    cred = await mqtt_credentials(["mesh/+/up", "mesh/priv/#"])
    received: list = []

    async def watch_remote(stop: asyncio.Event):
        async with aiomqtt.Client(hostname=REMOTE_HOST, port=1883,
                                  identifier=f"watch-{uuid.uuid4().hex[:6]}") as rc:
            await rc.subscribe("gw/mesh/#")
            agen = rc.messages.__aiter__()
            while not stop.is_set():
                try:
                    msg = await asyncio.wait_for(anext(agen), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                received.append((str(msg.topic), bytes(msg.payload)))

    stop = asyncio.Event()
    watcher = asyncio.create_task(watch_remote(stop))
    await asyncio.sleep(0.5)

    ok_topic = f"mesh/{uuid.uuid4().hex[:6]}/up"
    await publish_mqtt(ok_topic, b'{"v":1}', cred["username"], cred["password"])
    priv_topic = f"mesh/priv/{uuid.uuid4().hex[:6]}"
    await publish_mqtt(priv_topic, b"secret", cred["username"], cred["password"])
    await publish_mqtt(f"mesh/{uuid.uuid4().hex[:6]}/up", b'{"loop":1}',
                       cred["username"], cred["password"],
                       user_props=[("mg_origin", f"bridge:{bid}")])

    await asyncio.sleep(2.5)
    stop.set()
    try:
        await asyncio.wait_for(watcher, timeout=5)
    except asyncio.TimeoutError:
        watcher.cancel()

    topics_on_remote = [t for t, _ in received]
    assert any(t == f"gw/{ok_topic}" for t in topics_on_remote), received
    assert not any(priv_topic in t for t in topics_on_remote), received

    events = (await admin.get(f"{API}/v1/bridges/{bid}/events")).json()["data"]
    decisions = {e["decision"] for e in events}
    assert "reject" in decisions
    assert "loop_blocked" in decisions
    rejected = [e for e in events if e["decision"] == "reject"]
    assert any("лични" in e["reason"] for e in rejected)

    await admin.post(f"{API}/v1/bridges/{bid}/disable")
    await admin.delete(f"{API}/v1/bridges/{bid}")


# ---------- външна интеграция (модул за адаптация към друга система) ----------

async def test_integration_module(admin, mqtt_credentials):
    r = await admin.post(f"{API}/v1/integration/tokens",
                         json={"name": f"nms-{uuid.uuid4().hex[:6]}",
                               "can_publish": True, "allowed_topics": ["ext/+/data"]})
    assert r.status_code == 201, r.text
    token = r.json()["data"]["token"]
    token_id = r.json()["data"]["id"]
    hdr = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as c:
        r = await c.get(f"{API}/v1/integration/status", headers=hdr)
        assert r.status_code == 200
        assert r.json()["data"]["broker"]["connections"] >= 1
        r = await c.get(f"{API}/v1/integration/devices", headers=hdr)
        assert r.status_code == 200

        topic = f"ext/{uuid.uuid4().hex[:6]}/data"
        r = await c.post(f"{API}/v1/integration/publish", headers=hdr,
                         json={"topic": topic, "payload": "hello-from-nms"})
        assert r.status_code == 200, r.text
        await asyncio.sleep(1.2)
        r = await c.get(f"{API}/v1/integration/packets", headers=hdr,
                        params={"topic": topic})
        assert any(p["topic"] == topic for p in r.json()["data"])

        r = await c.post(f"{API}/v1/integration/publish", headers=hdr,
                         json={"topic": "mesh/other/up", "payload": "x"})
        assert r.status_code == 403

        r = await c.get(f"{API}/v1/integration/status")
        assert r.status_code == 401

    await admin.delete(f"{API}/v1/integration/tokens/{token_id}")
