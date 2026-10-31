"""Фаза 5 (първи срез): известия по време на жив поток (docs/12 §приемка)."""
import asyncio
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from conftest import ITEST as ADMIN, ensure_itest_admin
from test_checklist import API, login, publish_mqtt

PORT = 8899


class _Hook(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        try:
            _Hook.received.append(json.loads(body.decode()))
        except Exception:
            _Hook.received.append({"raw": body.decode("utf-8", "replace")})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):  # мълчи в тестовия изход
        pass


@pytest.fixture
async def hook_server():
    _Hook.received = []
    srv = HTTPServer(("127.0.0.1", PORT), _Hook)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield PORT
    srv.shutdown()


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


@pytest.fixture
async def mqtt_all(admin):
    username = f"nt-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/broker/credentials",
                         json={"username": username, "topics": ["#"]})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    yield {"username": username, "password": data["password"]}
    rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
    for row in rows:
        if row["username"] == username:
            await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


async def test_webhook_notification_end_to_end(admin, hook_server, mqtt_all):
    """alerts/# → webhook: публикуваме аларма, получателят я хваща."""
    name = f"hook-{uuid.uuid4().hex[:6]}"
    r = await admin.post(f"{API}/v1/notifications", json={
        "name": name, "kind": "webhook",
        "topic_pattern": "alerts/#",
        "config": {"url": f"http://127.0.0.1:{PORT}/hook"},
        "min_interval_s": 0, "enabled": True, "allow_internal": True,
    })
    assert r.status_code == 201, r.text

    # SSRF: webhook към loopback без allow_internal се отказва
    r2 = await admin.post(f"{API}/v1/notifications", json={
        "name": name + "-x", "kind": "webhook", "topic_pattern": "alerts/#",
        "config": {"url": "http://127.0.0.1:1/nope"},
    })
    assert r2.status_code == 422

    topic = f"alerts/test/{uuid.uuid4().hex[:6]}"
    await publish_mqtt(topic, json.dumps({"text": "ниска батерия", "battery": 5}),
                       mqtt_all["username"], mqtt_all["password"])

    deadline = time.time() + 15
    while time.time() < deadline:
        if any(h.get("topic") == topic for h in _Hook.received):
            break
        await asyncio.sleep(0.4)
    hits = [h for h in _Hook.received if h.get("topic") == topic]
    assert hits, "webhookът не получи известие"
    assert "ниска батерия" in hits[0]["message"]
    assert hits[0]["source"] == "meshgate"

    # журналът отразява изпращането
    log = (await admin.get(f"{API}/v1/notifications/log?limit=20")).json()["data"]
    assert any(l["topic"] == topic and l["status"] == "sent" for l in log), log[:5]

    # изтриване
    cid = next(c["id"] for c in
               (await admin.get(f"{API}/v1/notifications")).json()["data"]
               if c["name"] == name)
    assert (await admin.delete(f"{API}/v1/notifications/{cid}")).status_code == 200


async def test_channel_validation_and_test_button(admin, hook_server):
    """Невалидна конфигурация се отказва; тест-бутонът праща до webhookа."""
    r = await admin.post(f"{API}/v1/notifications", json={
        "name": f"bad-{uuid.uuid4().hex[:6]}", "kind": "telegram",
        "topic_pattern": "alerts/#", "config": {"bot_token": ""},
    })
    assert r.status_code == 422

    name = f"tst-{uuid.uuid4().hex[:6]}"
    r = await admin.post(f"{API}/v1/notifications", json={
        "name": name, "kind": "webhook", "topic_pattern": "t/#",
        "config": {"url": f"http://127.0.0.1:{PORT}/hook"},
        "allow_internal": True,
    })
    assert r.status_code == 201, r.text
    cid = r.json()["data"]["id"]

    assert (await admin.post(f"{API}/v1/notifications/{cid}/test")).status_code == 200
    deadline = time.time() + 10
    while time.time() < deadline and not _Hook.received:
        await asyncio.sleep(0.3)
    assert any("Тестово известие" in h.get("message", "") for h in _Hook.received)
    await admin.delete(f"{API}/v1/notifications/{cid}")


async def test_whatsapp_kind_and_template_roundtrip(admin, hook_server, mqtt_all):
    """WhatsApp (CallMeBot) канал: валидация + шаблон се пази и ползва."""
    # phone с букви → 422
    r = await admin.post(f"{API}/v1/notifications", json={
        "name": f"wa-{uuid.uuid4().hex[:6]}", "kind": "whatsapp",
        "topic_pattern": "alerts/#",
        "config": {"phone": "088abc", "apikey": "k"},
    })
    assert r.status_code == 422

    # валиден канал със собствен шаблон
    name = f"wa-{uuid.uuid4().hex[:6]}"
    tpl = "⚠ {node}: {text} (бат. {battery})"
    r = await admin.post(f"{API}/v1/notifications", json={
        "name": name, "kind": "whatsapp", "topic_pattern": "alerts/#",
        "config": {"phone": "+359888123456", "apikey": "secret-key"},
        "template": tpl, "min_interval_s": 0, "enabled": True,
    })
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["template"] == tpl
    assert data["config"]["apikey"] == "***"  # тайните не се връщат

    # каналът е в списъка на двигателя (зареден с template)
    listing = (await admin.get(f"{API}/v1/notifications")).json()["data"]
    ch = next(c for c in listing if c["name"] == name)
    assert ch["template"] == tpl

    # тест-бутонът към CallMeBot с фалшив ключ → честен провал в журнала
    tr = await admin.post(f"{API}/v1/notifications/{ch['id']}/test")
    assert tr.status_code in (200, 502)  # 502 при неотвоварящ/отказващ сервис
    log = (await admin.get(f"{API}/v1/notifications/log?limit=10")).json()["data"]
    assert any(l["channel"] == name and l["status"] in ("sent", "failed") for l in log)

    await admin.delete(f"{API}/v1/notifications/{ch['id']}")
