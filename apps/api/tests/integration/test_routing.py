"""Routing Rules — интеграционни тестове (docs/09-routing-rules-plan.md §8,
критерии 2–12). Пускат се ВЪТРЕ в api контейнера срещу живия стек."""

import asyncio
import time
import uuid

import httpx
import pytest

from conftest import ITEST as ADMIN, ensure_itest_admin
from test_checklist import API, REMOTE_HOST, login, publish_mqtt


async def _mk_rule(admin, definition: dict) -> str:
    r = await admin.post(f"{API}/v1/routing", json={"definition": definition})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def _defn(name, include, dest_topic, exclude=None, payload_terms=None,
          transform=None, destinations=None, priority=100):
    d = {
        "name": name,
        "priority": priority,
        "source": {"topic_filter": include[0] if "#" in include[0] else "mesh/#"},
        "conditions": {
            "topic": {"include": include, "exclude": exclude or []},
            "payload": {"terms": payload_terms or []},
        },
        "destinations": destinations
        or [{"type": "mqtt", "target": "local", "topic_template": dest_topic, "qos": 0}],
    }
    if transform:
        d["transform"] = transform
    return d


async def _packet_seen(admin, substr: str, timeout_s: float = 10.0) -> bool:
    """Изчаква пакет с тема съдържаща substr да се появи в базата."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = await admin.get(f"{API}/v1/packets", params={"topic": substr, "limit": 5})
        if r.json().get("data"):
            return True
        await asyncio.sleep(0.4)
    return False


async def _no_packet(admin, substr: str, wait_s: float = 2.0) -> bool:
    await asyncio.sleep(wait_s)
    r = await admin.get(f"{API}/v1/packets", params={"topic": substr, "limit": 5})
    return not r.json().get("data")


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


@pytest.fixture
async def mqtt_all(admin):
    """Креденшъли за публикуване навсякъде (създава/трие през API-то)."""
    username = f"rt-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/broker/credentials",
                         json={"username": username, "topics": ["#"]})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    yield {"username": username, "password": data["password"]}
    rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
    for row in rows:
        if row["username"] == username:
            await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


@pytest.fixture
async def cleanup_rules(admin):
    created: list[str] = []
    yield created
    for rid in created:
        await admin.post(f"{API}/v1/routing/{rid}/disable")
        await admin.delete(f"{API}/v1/routing/{rid}")


# ---------- критерий 2: topic include препраща само съответстващи ----------

async def test_c2_topic_include_forwards_only_matching(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    rid = await _mk_rule(admin, _defn(f"c2-{zone}", [f"mesh/{zone}/#"],
                                      f"routed/{zone}/{{topic}}"))
    cleanup_rules.append(rid)
    r = await admin.post(f"{API}/v1/routing/{rid}/enable")
    assert r.status_code == 200

    await publish_mqtt(f"mesh/{zone}/dev1/up", b'{"v":1}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"routed/{zone}/mesh"), "няма препратен пакет"

    await publish_mqtt(f"mesh/{zone}X/dev1/up", b'{"v":1}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _no_packet(admin, f"routed/{zone}/mesh/{zone}X")


# ---------- критерий 3: exclude има приоритет над include ----------

async def test_c3_exclude_wins(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    rid = await _mk_rule(admin, _defn(
        f"c3-{zone}", [f"mesh/{zone}/#"], f"r/{zone}/{{topic}}",
        exclude=[f"mesh/{zone}/priv/#"]))
    cleanup_rules.append(rid)
    await admin.post(f"{API}/v1/routing/{rid}/enable")

    await publish_mqtt(f"mesh/{zone}/priv/x", b"secret",
                       mqtt_all["username"], mqtt_all["password"])
    assert await _no_packet(admin, f"r/{zone}/mesh/{zone}/priv")

    await publish_mqtt(f"mesh/{zone}/pub/x", b"ok",
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"r/{zone}/mesh/{zone}/pub")


# ---------- критерий 4: payload условие върху реален пакет ----------

async def test_c4_payload_condition(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    rid = await _mk_rule(admin, _defn(
        f"c4-{zone}", [f"mesh/{zone}/+/up"], f"lowbat/{zone}/{{topic}}",
        payload_terms=[{"path": "$.battery", "op": "lt", "value": 20}]))
    cleanup_rules.append(rid)
    await admin.post(f"{API}/v1/routing/{rid}/enable")

    await publish_mqtt(f"mesh/{zone}/n1/up", b'{"battery": 80}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _no_packet(admin, f"lowbat/{zone}")

    await publish_mqtt(f"mesh/{zone}/n2/up", b'{"battery": 15}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"lowbat/{zone}/mesh")


# ---------- критерий 5: transform подменя темата и добавя поле ----------

async def test_c5_transform_topic_and_field(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    rid = await _mk_rule(admin, _defn(
        f"c5-{zone}", [f"mesh/{zone}/+/up"], "unused",
        transform={"topic_template": f"out/{zone}/{{topic_tokens[2]}}",
                   "set_fields": {"severity": "warning"}},
        destinations=[{"type": "mqtt", "target": "local",
                       "topic_template": f"out/{zone}/{{topic_tokens[2]}}", "qos": 0}]))
    cleanup_rules.append(rid)
    await admin.post(f"{API}/v1/routing/{rid}/enable")

    await publish_mqtt(f"mesh/{zone}/node7/up", b'{"battery": 50}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"out/{zone}/node7")

    # полето severity е в изходния payload
    r = await admin.get(f"{API}/v1/packets", params={"topic": f"out/{zone}/node7"})
    pid = r.json()["data"][0]["id"]
    detail = (await admin.get(f"{API}/v1/packets/{pid}")).json()["data"]
    assert "severity" in (detail.get("payload_text") or "")


# ---------- критерий 6: две дестинации (локална + bridge) ----------

async def test_c6_two_destinations(admin, mqtt_all, cleanup_rules):
    import aiomqtt

    zone = uuid.uuid4().hex[:6]
    # bridge към remote-broker (тестов профил)
    r = await admin.post(f"{API}/v1/bridges",
                         json={"name": f"rb-{zone}", "remote_host": REMOTE_HOST,
                               "allow_internal": True, "rate_limit_per_min": 100,
                               "rules": [{"kind": "allow", "topic_pattern": "#"}]})
    assert r.status_code == 201, r.text
    bid = r.json()["data"]["id"]
    try:
        await admin.post(f"{API}/v1/bridges/{bid}/enable")
        await asyncio.sleep(2)

        received: list = []

        async def watch_remote(stop: asyncio.Event):
            async with aiomqtt.Client(hostname=REMOTE_HOST, port=1883,
                                      identifier=f"w-{zone}") as rc:
                await rc.subscribe("#")
                agen = rc.messages.__aiter__()
                while not stop.is_set():
                    try:
                        msg = await asyncio.wait_for(anext(agen), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    received.append(str(msg.topic))

        stop = asyncio.Event()
        watcher = asyncio.create_task(watch_remote(stop))
        await asyncio.sleep(0.5)

        rid = await _mk_rule(admin, _defn(
            f"c6-{zone}", [f"mesh/{zone}/#"], "unused",
            destinations=[
                {"type": "mqtt", "target": "local",
                 "topic_template": f"two/{zone}/{{topic}}", "qos": 0},
                {"type": "mqtt", "target": f"bridge:{bid}",
                 "topic_template": "{topic}", "qos": 1},
            ]))
        cleanup_rules.append(rid)
        await admin.post(f"{API}/v1/routing/{rid}/enable")

        topic = f"mesh/{zone}/x/up"
        await publish_mqtt(topic, b'{"v":1}', mqtt_all["username"], mqtt_all["password"])
        assert await _packet_seen(admin, f"two/{zone}/{topic}")

        await asyncio.sleep(2.5)
        stop.set()
        try:
            await asyncio.wait_for(watcher, timeout=5)
        except asyncio.TimeoutError:
            watcher.cancel()
        assert topic in received, received
    finally:
        await admin.post(f"{API}/v1/bridges/{bid}/disable")
        await admin.delete(f"{API}/v1/bridges/{bid}")


# ---------- критерий 7: dry-run връща trace без да публикува ----------

async def test_c7_dry_run_trace_no_publish(admin, mqtt_all):
    zone = uuid.uuid4().hex[:6]
    r = await admin.post(f"{API}/v1/routing/dry-run", json={
        "definition": _defn(f"c7-{zone}", [f"mesh/{zone}/+/up"], f"dry/{zone}/{{payload.node}}",
                            payload_terms=[{"path": "$.battery", "op": "lt", "value": 20}]),
        "topic": f"mesh/{zone}/n1/up",
        "payload": '{"battery": 15, "node": "n1"}',
    })
    assert r.status_code == 200, r.text
    trace = r.json()["data"][0]
    assert trace["decision"] == "match_forward"
    assert trace["steps"], "trace-ът е празен"
    assert trace["outputs"][0]["topic"] == f"dry/{zone}/n1"
    assert await _no_packet(admin, f"dry/{zone}/")


# ---------- критерий 8: disabled правило не се изпълнява ----------

async def test_c8_disabled_rule_skips(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    rid = await _mk_rule(admin, _defn(f"c8-{zone}", [f"mesh/{zone}/#"], f"off/{zone}/{{topic}}"))
    cleanup_rules.append(rid)  # НЕ го включваме

    await publish_mqtt(f"mesh/{zone}/a/up", b'{"v":1}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _no_packet(admin, f"off/{zone}/")

    await admin.post(f"{API}/v1/routing/{rid}/enable")
    await publish_mqtt(f"mesh/{zone}/b/up", b'{"v":1}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"off/{zone}/mesh/{zone}/b")


# ---------- критерий 9: версии — publish v2, rollback v1 ----------

async def test_c9_versions_and_rollback(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    rid = await _mk_rule(admin, _defn(f"c9-{zone}", [f"mesh/{zone}/#"], f"v1/{zone}/{{topic}}"))
    cleanup_rules.append(rid)
    await admin.post(f"{API}/v1/routing/{rid}/enable")

    await publish_mqtt(f"mesh/{zone}/m1/up", b'{"v":1}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"v1/{zone}/mesh/{zone}/m1")

    # draft с нова дестинация -> publish v2
    d2 = _defn(f"c9-{zone}", [f"mesh/{zone}/#"], f"v2/{zone}/{{topic}}")
    d2["name"] = f"c9-{zone}"  # името не се сменя
    r = await admin.patch(f"{API}/v1/routing/{rid}", json={"definition": d2})
    assert r.status_code == 200, r.text
    r = await admin.post(f"{API}/v1/routing/{rid}/publish", json={"note": "v2"})
    assert r.status_code == 200 and r.json()["data"]["published_version"] == 2

    await publish_mqtt(f"mesh/{zone}/m2/up", b'{"v":2}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"v2/{zone}/mesh/{zone}/m2")

    # rollback към v1
    r = await admin.post(f"{API}/v1/routing/{rid}/rollback", json={"version": 1})
    assert r.status_code == 200 and r.json()["data"]["published_version"] == 3
    await publish_mqtt(f"mesh/{zone}/m3/up", b'{"v":3}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"v1/{zone}/mesh/{zone}/m3")
    assert await _no_packet(admin, f"v2/{zone}/mesh/{zone}/m3")


# ---------- критерий 10: цикъл — origin marker не се препретъка ----------

async def test_c10_loop_marker_blocks_reprocessing(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    # include умишлено хваща и изхода — спира ни origin marker-ът
    rid = await _mk_rule(admin, _defn(f"c10-{zone}", [f"loop/{zone}/#"],
                                      f"loop/{zone}/out/{{topic}}"))
    cleanup_rules.append(rid)
    await admin.post(f"{API}/v1/routing/{rid}/enable")

    await publish_mqtt(f"loop/{zone}/a", b'{"v":1}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"loop/{zone}/out/loop/{zone}/a")
    await asyncio.sleep(3)
    # втори скок би дал тема с ВТОРО "out/loop/" в нея — такава не бива да има
    r = await admin.get(f"{API}/v1/packets", params={"topic": "out/loop/", "limit": 50})
    hops = [p["topic"] for p in r.json()["data"] if p["topic"].count("out/loop/") > 1]
    assert not hops, f"открит цикъл: {hops}"

    execs = (await admin.get(f"{API}/v1/routing/{rid}/executions",
                             params={"decision": "match_forward"})).json()["data"]
    assert execs, "журналът на изпълненията е празен"


# ---------- критерий 11: провалена дестинация не спира другите ----------

async def test_c11_failed_destination_continues(admin, mqtt_all, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    ghost = str(uuid.uuid4())  # несъществуващ/неактивен bridge
    rid = await _mk_rule(admin, _defn(
        f"c11-{zone}", [f"mesh/{zone}/#"], "unused",
        destinations=[
            {"type": "mqtt", "target": f"bridge:{ghost}",
             "topic_template": "{topic}", "qos": 0},
            {"type": "mqtt", "target": "local",
             "topic_template": f"ok/{zone}/{{topic}}", "qos": 0},
        ]))
    cleanup_rules.append(rid)
    await admin.post(f"{API}/v1/routing/{rid}/enable")

    await publish_mqtt(f"mesh/{zone}/x/up", b'{"v":1}',
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"ok/{zone}/mesh/{zone}/x"), \
        "локалната дестинация трябваше да получи съобщението въпреки проваления bridge"

    execs = (await admin.get(f"{API}/v1/routing/{rid}/executions")).json()["data"]
    assert any("грешка при" in " ".join(s.get("step", "") for s in e["steps"])
               for e in execs), execs


# ---------- критерий 12: RBAC + audit ----------

async def test_c12_rbac_and_audit(admin, cleanup_rules):
    zone = uuid.uuid4().hex[:6]
    rid = await _mk_rule(admin, _defn(f"c12-{zone}", [f"mesh/{zone}/#"], f"rbac/{zone}/{{topic}}"))
    cleanup_rules.append(rid)

    # operator: може dry-run и enable, не може create/publish/patch
    op = f"op-{uuid.uuid4().hex[:6]}"
    r = await admin.post(f"{API}/v1/users",
                         json={"username": op, "password": "op-pass-123", "role": "operator"})
    assert r.status_code == 201
    async with httpx.AsyncClient() as c:
        await login(c, {"username": op, "password": "op-pass-123"})
        assert (await c.post(f"{API}/v1/routing/dry-run",
                             json={"rule_id": rid, "topic": f"mesh/{zone}/a",
                                   "payload": "{}"})).status_code == 200
        assert (await c.post(f"{API}/v1/routing/{rid}/enable")).status_code == 200
        assert (await c.post(f"{API}/v1/routing",
                             json={"definition": _defn("nope", ["x/#"], "y/{topic}")})
                ).status_code == 403
        assert (await c.post(f"{API}/v1/routing/{rid}/publish")).status_code == 403
        assert (await c.patch(f"{API}/v1/routing/{rid}",
                              json={"definition": _defn(f"c12-{zone}", [f"mesh/{zone}/#"], "z/{topic}")})
                ).status_code == 403

    # viewer: само четене
    vw = f"vw-{uuid.uuid4().hex[:6]}"
    await admin.post(f"{API}/v1/users",
                    json={"username": vw, "password": "vw-pass-123", "role": "viewer"})
    async with httpx.AsyncClient() as c:
        await login(c, {"username": vw, "password": "vw-pass-123"})
        assert (await c.get(f"{API}/v1/routing")).status_code == 200
        assert (await c.post(f"{API}/v1/routing/{rid}/disable")).status_code == 403

    # audit записите за routing действия съществуват
    actions = set()
    r = await admin.get(f"{API}/v1/audit", params={"limit": 200})
    for row in r.json()["data"]:
        if row["action"].startswith("routing."):
            actions.add(row["action"])
    assert {"routing.create", "routing.enable"} <= actions


# ---------- регресия: шаблоните са ПЪЛНИ дефиниции (не чупят wizard-а) ----------

async def test_templates_are_complete_definitions(admin):
    from app.routing.model import RuleDefinition

    r = await admin.get(f"{API}/v1/routing/templates")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) >= 7
    for t in data:
        # всяко поле със schema default присъства — без MissingError
        d = RuleDefinition(**t["definition"])
        assert d.conditions.payload is not None
        assert d.transform is not None
        assert d.error_policy is not None
        assert d.destinations
    r = await admin.get(f"{API}/v1/routing/samples")
    assert r.status_code == 200 and isinstance(r.json()["data"], list)


# ---------- R2: HTTP дестинация — SSRF вратичката при запис ----------

async def test_http_destination_ssrf_guard(admin, cleanup_rules):
    """Вътрешни (loopback) адреси не се допускат; външен https минава."""
    defn = {
        "name": f"hook-{uuid.uuid4().hex[:6]}",
        "priority": 100,
        "source": {"topic_filter": "in/#"},
        "conditions": {"topic": {"include": ["in/#"]}},
        "destinations": [{
            "type": "http", "target": "http",
            "topic_template": "{topic}", "qos": 0, "retain": False,
            "url": "http://127.0.0.1:8899/hook",
        }],
    }
    r = await admin.post(f"{API}/v1/routing", json={"definition": defn})
    assert r.status_code == 422, r.text

    defn["name"] = f"hook-{uuid.uuid4().hex[:6]}"
    defn["destinations"][0]["url"] = "http://192.168.1.9/internal"
    r2 = await admin.post(f"{API}/v1/routing", json={"definition": defn})
    assert r2.status_code == 422  # частна мрежа също е заключена

    defn["name"] = f"hook-{uuid.uuid4().hex[:6]}"
    defn["destinations"][0]["url"] = "https://ntfy.sh/my-topic"
    r3 = await admin.post(f"{API}/v1/routing", json={"definition": defn})
    assert r3.status_code == 201, r3.text
    cleanup_rules.append(r3.json()["data"]["id"])


# ---------- R2: retry + dead-letter + повторно изпращане ----------

async def test_dead_letter_and_resend(admin, mqtt_all, cleanup_rules):
    """Провалена дестинация (несъществуващ мост): retry, после мъртва буква;
    повторното изпращане на мъртва буква с локална цел доставя оригинала."""
    import base64 as _b64
    import json as _json

    bad_bridge = str(uuid.uuid4())
    name = f"dl-{uuid.uuid4().hex[:6]}"
    rid = await _mk_rule(admin, _defn(
        name, [f"dl-test/{name}/#"], "resend-should-not-appear/{topic_suffix[2]}",
        destinations=[
            {"type": "mqtt", "target": f"bridge:{bad_bridge}",
             "topic_template": "out/{topic}", "qos": 0},
        ],
        priority=10,
    ))
    cleanup_rules.append(rid)
    # retry 1 (2 опита, 100ms пауза) + dead-letter
    r = await admin.patch(f"{API}/v1/routing/{rid}", json={"definition": {
        **_defn(name, [f"dl-test/{name}/#"], "out/{topic}",
                destinations=[{"type": "mqtt", "target": f"bridge:{bad_bridge}",
                               "topic_template": "out/{topic}", "qos": 0}]),
        "error_policy": {"on_destination_failure": "continue",
                         "retry": {"max": 1, "backoff_ms": 100},
                         "dead_letter": True},
    }})
    assert r.status_code == 200, r.text
    await admin.post(f"{API}/v1/routing/{rid}/publish", json={"note": "dl тест"})
    await admin.post(f"{API}/v1/routing/{rid}/enable")

    topic = f"dl-test/{name}/hello"
    await publish_mqtt(topic, "original-payload", mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"deadletter/{name}", timeout_s=15)

    # журналът показва retry и dead-letter стъпките
    execs = (await admin.get(f"{API}/v1/routing/{rid}/executions",
                             params={"limit": 5})).json()["data"]
    steps = [s["step"] for e in execs for s in (e.get("steps") or [])]
    assert any("след 2 опита" in s for s in steps), steps[:8]
    assert any("deadletter/" in s for s in steps), steps[:8]

    # повторно изпращане: мъртва буква с ЛОКАЛНА цел (пътят на resend)
    dl_rows = (await admin.get(f"{API}/v1/packets",
                               params={"topic": f"deadletter/{name}", "limit": 1})
               ).json()["data"]
    assert dl_rows
    # подменяме целта в плика с локална, за да проверим resend без мост:
    # публикуваме собствена мъртва буква ръчно (както би изглеждала)
    manual = _json.dumps({
        "rule": name, "input_topic": topic, "target": "local",
        "topic": f"resend-ok/{name}", "qos": 0, "retain": False,
        "error": "недостъпен",
        "payload_b64": _b64.b64encode(b"resent-payload").decode(),
    })
    await publish_mqtt(f"deadletter/{name}-manual", manual,
                       mqtt_all["username"], mqtt_all["password"])
    assert await _packet_seen(admin, f"deadletter/{name}-manual")
    pk = (await admin.get(f"{API}/v1/packets",
                          params={"topic": f"deadletter/{name}-manual", "limit": 1})
          ).json()["data"][0]
    rr = await admin.post(f"{API}/v1/routing/deadletter/resend",
                          json={"packet_id": pk["id"]})
    assert rr.status_code == 200, rr.text
    assert rr.json()["data"]["topic"] == f"resend-ok/{name}"
    assert await _packet_seen(admin, f"resend-ok/{name}")

    # resend на непознат packet_id → 404
    r404 = await admin.post(f"{API}/v1/routing/deadletter/resend",
                            json={"packet_id": str(uuid.uuid4())})
    assert r404.status_code == 404

    # мъртвите букви на тестовите правила (dl-*/c11-* по конвенция) не
    # бива да замърсяват сутрешния бриф на оператора — чистим ги накрая
    from app.config import settings as app_settings
    from app.db import connect as db_connect

    pool = await db_connect()
    try:
        await pool.execute(
            "DELETE FROM packets WHERE topic LIKE 'deadletter/dl-%'"
            " OR topic LIKE 'deadletter/c11-%'")
    finally:
        await pool.close()


# ---------- Т26: hold-back + „Изпрати сега" ----------

async def test_c26_hold_back_flush_delivers(admin, mqtt_all, cleanup_rules):
    """Живата верификация на Т26: normal доставки на възел с hold_back се
    задържат; flush ги доставя; urgent/critic минават (класът е Т25)."""
    zone = uuid.uuid4().hex[:6]
    node = f"!hb{uuid.uuid4().hex[:6]}"
    rid = await _mk_rule(admin, _defn(f"hb-{zone}", [f"mesh/{zone}/#"],
                                      f"routed/{zone}/{{topic}}"))
    cleanup_rules.append(rid)
    r = await admin.post(f"{API}/v1/routing/{rid}/enable")
    assert r.status_code == 200

    # 1) devices ред за тестовия възел — директно в базата (ingest-ът
    # създава устройства само от msh/* теми, а живата база има 600+ реда,
    # затова и търсенето в списъка е ненадеждно)
    import asyncpg, os
    conn = await asyncpg.connect(
        host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        database=os.environ["PGDATABASE"])
    try:
        dev_id = await conn.fetchval(
            "INSERT INTO devices (protocol, external_id, name, status)"
            " VALUES ('meshtastic', $1, $1, 'online')"
            " ON CONFLICT (protocol, external_id) DO UPDATE SET status='online'"
            " RETURNING id", node)
    finally:
        await conn.close()
    dev = {"id": str(dev_id), "external_id": node}
    r = await admin.post(f"{API}/v1/devices/{dev['id']}/hold-back",
                         json={"hold_back": True})
    assert r.status_code == 200, r.text

    try:
        # 2) втори пакет — normal доставка се ЗАДЪРЖА (не достига до routed/)
        await publish_mqtt(f"mesh/{zone}/{node}/up", b'{"v":2}',
                           mqtt_all["username"], mqtt_all["password"])
        deadline = time.time() + 10.0
        held = 0
        while time.time() < deadline:
            r = await admin.get(f"{API}/v1/routing/hold-back")
            held = r.json()["data"]["held"]
            if held >= 1:
                break
            await asyncio.sleep(0.4)
        assert held >= 1, "задържана доставка липсва"

        # 3) flush — „Изпрати сега" доставя и бройката опада до 0;
        # финалното доказателство: пакетът СЕ ПОЯВЯВА на routed/ (пътят
        # hold -> flush -> local publish -> ingest)
        r = await admin.post(f"{API}/v1/routing/hold-back/flush")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["delivered"] >= 1, r.text
        r = await admin.get(f"{API}/v1/routing/hold-back")
        assert r.json()["data"]["held"] == 0
        deadline = time.time() + 10.0
        n = 0
        while time.time() < deadline:
            r = await admin.get(f"{API}/v1/packets",
                                params={"topic": f"routed/{zone}/mesh/{zone}/{node}",
                                        "limit": 10})
            n = len(r.json().get("data") or [])
            if n >= 1:
                break
            await asyncio.sleep(0.4)
        assert n >= 1, f"flush доставката липсва ({n} реда на routed/)"
    finally:
        await admin.post(f"{API}/v1/devices/{dev['id']}/hold-back",
                         json={"hold_back": False})
