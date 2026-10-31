"""Т7 интеграционен тест: критични събития на жив стек (демо батерии 5%).

Използва емулаторните възли (батерия 5% < праг 20) като реален източник:
open → ack → silence → (изтекъл) wake → resolved (праг 0) → reopen.
RBAC: временен viewer потребител не може да ack-ва.
"""
import asyncio
import json
import os

import asyncpg
import httpx
import pytest

from conftest import ITEST, ensure_itest_admin
from test_checklist import API, login

TICK_WAIT_S = 6.0  # тестовият профил върти evaluator на 2s


async def _wait_for(predicate, timeout_s=60.0, interval=1.0):
    """Въртим докато predicate() стане истина (evaluator цикъл + API).
    Щедър timeout: при пълен набор events таблицата е подута от другите
    тестове и цикълът на evaluator-а се бави (указаният tick не е гаранция)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last = None
    while asyncio.get_event_loop().time() < deadline:
        last = await predicate()
        if last:
            return last
        await asyncio.sleep(interval)
    return last


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ITEST)
        yield c


@pytest.fixture
async def db():
    conn = await asyncpg.connect(
        host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        database=os.environ["PGDATABASE"])
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
async def clean_and_restore(db, admin):
    """Тестовете чистят своите събития и връщат праговете."""
    yield
    await db.execute("DELETE FROM critical_events")
    await db.execute("DELETE FROM settings WHERE key = 'critical'")
    await db.execute("DELETE FROM events WHERE device_id IN"
                     " (SELECT id FROM devices WHERE external_id = '!t7-bat-test')")
    await db.execute("DELETE FROM devices WHERE external_id = '!t7-bat-test'")


async def _counts(c: httpx.AsyncClient) -> dict:
    r = await c.get(f"{API}/v1/critical-events")
    assert r.status_code == 200, r.text
    return r.json()["data"]["counts"]


async def test_battery_events_open_ack_silence_resolve_reopen(admin, db):
    # 1) детерминирана фикстура: тестов възел с 5% батерия (емулаторът е
    #    спрян по подразбиране — собственик 30.10 — тестът не зависи от него)
    TEST_NODE = "!t7-bat-test"
    await db.execute(
        "INSERT INTO devices (protocol, external_id, name, status)"
        " VALUES ('meshtastic', $1, $1, 'online')"
        " ON CONFLICT (protocol, external_id) DO UPDATE SET last_seen_at = now()",
        TEST_NODE)
    dev_id = await db.fetchval(
        "SELECT id FROM devices WHERE external_id = $1", TEST_NODE)
    await db.execute(
        "INSERT INTO events (device_id, source, event_type, payload)"
        " VALUES ($1, 'test', 'telemetry', $2::jsonb)",
        dev_id, json.dumps({"decoded": {"node": TEST_NODE, "battery": 5}}))
    await db.execute("DELETE FROM critical_events WHERE event_key = $1",
                     f"battery:{TEST_NODE}")

    async def has_open():
        r2 = await admin.get(f"{API}/v1/critical-events?status=open&kind=battery")
        return any(e["event_key"] == f"battery:{TEST_NODE}"
                   for e in r2.json()["data"]["events"])
    assert await _wait_for(has_open), "фикстурата не роди battery събитие"

    r = await admin.get(f"{API}/v1/critical-events?status=open")
    events = r.json()["data"]["events"]
    assert all(e["kind"] in ("battery", "deadletter", "silence") for e in events)
    bat = next(e for e in events if e["event_key"] == f"battery:{TEST_NODE}")
    assert bat["payload"]["node"] and bat["payload"]["links"]

    # 2) ack → излиза от open
    r = await admin.post(f"{API}/v1/critical-events/{bat['event_key']}/ack")
    assert r.status_code == 200, r.text

    async def acked_gone():
        r2 = await admin.get(f"{API}/v1/critical-events?status=open")
        return bat["event_key"] not in [e["event_key"] for e in r2.json()["data"]["events"]]
    assert await _wait_for(acked_gone), "acked събитие остана в open"

    # 3) silence на друго събитие → silenced; изтичане директно в БД → wake
    r = await admin.get(f"{API}/v1/critical-events?status=open")
    others = [e for e in r.json()["data"]["events"] if e["kind"] == "battery"]
    if others:
        key = others[0]["event_key"]
        r = await admin.post(f"{API}/v1/critical-events/{key}/silence", json={"hours": 4})
        assert r.status_code == 200, r.text
        # изкуствено изтичане (без да чакаме 4 часа)
        await db.execute(
            "UPDATE critical_events SET silenced_until = now() - interval '1 second'"
            " WHERE event_key = $1", key)

        async def woke():
            r3 = await admin.get(f"{API}/v1/critical-events?status=open")
            return key in [e["event_key"] for e in r3.json()["data"]["events"]]
        assert await _wait_for(woke), "изтеклият silence не събуди събитието"

    # 4) праг 0 → батерийните условия изчезват → resolved
    #    (реалните BG възли държат легитимни silence събития — те ОСТАВАТ open)
    r = await admin.put(f"{API}/v1/critical-events/settings/thresholds",
                        json={"battery_pct": 0})
    assert r.status_code == 200, r.text

    async def battery_resolved():
        # ВАКУУМНА КЛУШКА беше тук: след ack няма open battery и проверката
        # минаваше мигновено, преди resolve; чака се ТОЧНО нашето събитие
        r2 = await admin.get(f"{API}/v1/critical-events?status=resolved&kind=battery&hours=168")
        return any(e["event_key"] == f"battery:{TEST_NODE}"
                   for e in r2.json()["data"]["events"])
    assert await _wait_for(battery_resolved), "батерийното събитие не се resolved при праг 0"

    r = await admin.get(f"{API}/v1/critical-events?status=resolved&kind=battery")
    assert r.json()["data"]["events"], "няма resolved батерийни събития"
    resolved_key = r.json()["data"]["events"][0]["event_key"]

    # 6) ack на resolved събитие → 409 (правилно отказан)
    r = await admin.post(f"{API}/v1/critical-events/{resolved_key}/ack")
    assert r.status_code == 409

    # 5) прага обратно → reopen с occurrences+1
    r = await admin.put(f"{API}/v1/critical-events/settings/thresholds",
                        json={"battery_pct": 20})
    assert r.status_code == 200, r.text

    async def reopened():
        # 407-те silence събития се refresh-ват всеки цикъл и при limit=100
        # изтласкват тестовия възел от списъка — филтърът е СЪРВЪРЕН
        r4 = await admin.get(f"{API}/v1/critical-events?status=open&kind=battery")
        evs = [e for e in r4.json()["data"]["events"]
               if e["event_key"] == f"battery:{TEST_NODE}"]
        return evs[0] if evs and evs[0]["occurrences"] >= 2 else None
    ev = await _wait_for(reopened)
    assert ev, "няма reopen (occurrences >= 2) след връщане на прага"


async def test_thresholds_validation_and_rbac(admin, db):
    r = await admin.put(f"{API}/v1/critical-events/settings/thresholds",
                        json={"battery_pct": 200})
    assert r.status_code == 422
    r = await admin.put(f"{API}/v1/critical-events/settings/thresholds",
                        json={"battery_pct": 15, "silence_hours": 24})
    assert r.status_code == 200
    r = await admin.get(f"{API}/v1/critical-events/settings/thresholds")
    eff = r.json()["data"]["effective"]
    assert eff["battery_pct"] == 15 and eff["silence_hours"] == 24
    assert eff["deadletter_24h"] == 3  # незасегнатият остава default

    # viewer не може да ack-ва
    await db.execute(
        "INSERT INTO users (username, password_hash, role, disabled)"
        " VALUES ('t7-viewer', $1, 'viewer', false)"
        " ON CONFLICT (username) DO UPDATE SET role='viewer', disabled=false",
        __import__("app.security", fromlist=["hash_password"]).hash_password("t7-pass-1234"))
    try:
        async with httpx.AsyncClient() as c:
            await login(c, {"username": "t7-viewer", "password": "t7-pass-1234"})
            r = await c.get(f"{API}/v1/critical-events")
            assert r.status_code == 200  # четене му е позволено
            r = await c.post(f"{API}/v1/critical-events/battery:!none/ack")
            assert r.status_code == 403
            r = await c.put(f"{API}/v1/critical-events/settings/thresholds",
                            json={"battery_pct": 1})
            assert r.status_code == 403
    finally:
        await db.execute("DELETE FROM users WHERE username = 't7-viewer'")


async def test_unknown_event_404(admin):
    r = await admin.post(f"{API}/v1/critical-events/battery:!ghost/ack")
    assert r.status_code == 404
