"""Фаза 3a: Meshtastic трафик се разпознава автоматично (docs/10 §3)."""

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


async def _find_packet(admin, ptype: str, timeout_s: float = 12.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = await admin.get(f"{API}/v1/packets", params={"limit": 60})
        for p in r.json()["data"]:
            if p["packet_type"] == ptype:
                return p
        import asyncio

        await asyncio.sleep(0.5)
    return None


async def test_meshtastic_traffic_recognized(admin, mqtt_all):
    node = f"!{uuid.uuid4().hex[:8]}"
    topic = f"msh/emul/2/e/LongFast/{node}"

    # 1) текстово съобщение
    await publish_mqtt(topic, json.dumps({
        "id": 42, "timestamp": int(time.time()), "to": -1,
        "from": 123456789, "sender": node, "channel": 0,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "тест от реална мрежа"},
    }), mqtt_all["username"], mqtt_all["password"])
    p = await _find_packet(admin, "meshtastic-text")
    assert p, "текстовият Meshtastic пакет не беше разпознат"
    assert p["decode_status"] == "decoded"
    assert p["topic"] == topic

    # 2) телеметрия с батерия → devices по възела + батерии в Мониторинга
    await publish_mqtt(topic, json.dumps({
        "id": 43, "to": -1, "from": 123456789, "sender": node, "channel": 0,
        "decoded": {"portnum": "TELEMETRY_APP",
                    "telemetry": {"device_metrics": {"battery_level": 7}}},
    }), mqtt_all["username"], mqtt_all["password"])
    p2 = await _find_packet(admin, "meshtastic-telemetry")
    assert p2, "телеметрията не беше разпозната"

    # устройство по възел (!hex), не по тема
    devs = (await admin.get(f"{API}/v1/devices")).json()["data"]
    assert any(d["external_id"] == node or node in str(d) for d in devs), devs[:5]

    # батерията се показва в мониторинг статистиките
    stats = (await admin.get(f"{API}/v1/stats/overview?hours=2")).json()["data"]
    assert any(node in b["node"] and b["battery"] == 7 for b in stats["batteries"]), \
        stats["batteries"][:6]

    # 3) каналът се групира човешки (msh/.../*) — не зависим от top-12
    # подредбата на families (живият BG мост + HA теми изтласкват
    # тестовото семейство); групирането се проверява директно през фасетите
    fams = [f["family"] for f in stats["families"]]
    assert any(f.startswith("msh/") for f in fams), fams[:8]
    facets = (await admin.get(f"{API}/v1/packets/facets", params={
        "hours": 2})).json()["data"]
    lf = next((c for c in facets["channels"] if c["channel"] == "LongFast"), None)
    assert lf and lf["count"] >= 1, facets["channels"][:8]


async def test_binary_protobuf_is_honest(admin, mqtt_all):
    """Binary payload върху msh/ тема → записва се, без да се преструва, че е декодирано."""
    topic = f"msh/emul/2/e/LongFast/!{uuid.uuid4().hex[:8]}"
    await publish_mqtt(topic, b"\xff\xfe\x08proto\x99", mqtt_all["username"], mqtt_all["password"])
    import asyncio

    await asyncio.sleep(2.0)
    r = await admin.get(f"{API}/v1/packets", params={"topic": topic, "limit": 3})
    data = r.json()["data"]
    assert data, "пакетът не беше записан"
    assert data[0]["packet_type"] == "binary"
    assert data[0]["decode_status"] == "not_attempted"


# ---------- 3b: бинарен protobuf ServiceEnvelope + дедупликация ----------

def _varint(n: int) -> bytes:
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _fld(no: int, wt: int) -> bytes:
    return _varint((no << 3) | wt)


def _pb_text_envelope(from_id: int, pkt_id: int, text: str) -> bytes:
    """ServiceEnvelope{packet{from, to=broadcast, id, decoded{TEXT_MESSAGE, payload}}}."""
    inner = text.encode("utf-8")
    data = _fld(1, 0) + _varint(1) + _fld(2, 2) + _varint(len(inner)) + inner
    pkt = (
        _fld(1, 5) + from_id.to_bytes(4, "little")
        + _fld(2, 5) + (0xFFFFFFFF).to_bytes(4, "little")
        + _fld(4, 0) + _varint(pkt_id)
        + _fld(12, 2) + _varint(len(data)) + data
    )
    return _fld(1, 2) + _varint(len(pkt)) + pkt


async def test_binary_protobuf_text_decoded(admin, mqtt_all):
    """Валиден бинарен ServiceEnvelope → разпознат текст с protobuf декодера."""
    node_num = int(uuid.uuid4().hex[:8], 16)
    topic = f"msh/emul/2/e/LongFast/!{node_num:08x}"
    await publish_mqtt(
        topic, _pb_text_envelope(node_num, 4242, "бинарно съобщение"),
        mqtt_all["username"], mqtt_all["password"],
    )
    deadline = time.time() + 12.0
    rows = []
    while time.time() < deadline:
        r = await admin.get(f"{API}/v1/packets", params={"topic": topic, "limit": 5})
        rows = [p for p in r.json()["data"] if p["packet_type"] == "meshtastic-text"]
        if rows:
            break
        await asyncio.sleep(0.5)
    assert rows, "бинарният protobuf текст не беше разпознат"
    assert rows[0]["decode_status"] == "decoded"


async def test_packet_id_dedupe(admin, mqtt_all):
    """Едно и също съобщение (същият packet id) през два „брокера“ → записва се веднъж."""
    node_num = int(uuid.uuid4().hex[:8], 16)
    node = f"!{node_num:08x}"
    env = _pb_text_envelope(node_num, 777777, "дублирано съобщение")
    await publish_mqtt(f"msh/emul/2/e/LongFast/{node}", env,
                       mqtt_all["username"], mqtt_all["password"])
    await asyncio.sleep(1.0)
    # втори „източник“ — същият packet id, друга тема (друг регион)
    await publish_mqtt(f"msh/emul2/2/e/LongFast/{node}", env,
                       mqtt_all["username"], mqtt_all["password"])
    await asyncio.sleep(2.0)

    r = await admin.get(f"{API}/v1/packets", params={"limit": 200})
    rows = [p for p in r.json()["data"] if p["packet_type"] == "meshtastic-text"
            and p["topic"].endswith(node)]
    assert rows, "първото копие не беше записано"
    ids = {p["topic"] for p in rows}
    assert f"msh/emul/2/e/LongFast/{node}" in ids
    assert f"msh/emul2/2/e/LongFast/{node}" not in ids, "повторът трябваше да се дедупликира"

    # броячът се вижда в мониторинг статистиката
    stats = (await admin.get(f"{API}/v1/stats/overview?hours=1")).json()["data"]
    assert stats.get("mesh_deduped", 0) >= 1
