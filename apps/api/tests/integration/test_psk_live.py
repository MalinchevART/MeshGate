"""Т36 срез 2 (ADR-007) интеграционно: криптиран ServiceEnvelope върху MQTT
→ ingest декриптира с ключа от /v1/system/psk → пакетът е meshtastic-text.
Пускат се срещу живия стек (MESHGATE_API отвън, exec отвътре)."""

import asyncio
import base64
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


def _encrypt(key: bytes, from_id: int, pkt_id: int, plaintext: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    nonce = pkt_id.to_bytes(8, "little") + from_id.to_bytes(4, "little") + b"\x00" * 4
    return Cipher(algorithms.AES(key), modes.CTR(nonce)).encryptor().update(plaintext)


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


@pytest.fixture
async def mqtt_all(admin):
    username = f"pk-{uuid.uuid4().hex[:8]}"
    r = await admin.post(f"{API}/v1/broker/credentials",
                         json={"username": username, "topics": ["#"]})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    yield {"username": username, "password": data["password"]}
    rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
    for row in rows:
        if row["username"] == username:
            await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")


async def test_encrypted_envelope_decodes_with_psk(admin, mqtt_all):
    """Ключът се записва НА ЖИВО през API-то → публикуваме криптиран
    ServiceEnvelope → декодиран текст в базата. Накрая ключът се маха."""
    zone = uuid.uuid4().hex[:6]
    channel = f"PSK{zone}"
    from_id = int(uuid.uuid4().hex[:8], 16)
    node = f"!{from_id:08x}"
    key = bytes(range(16))
    text = f"пски-тест-{zone}"

    r = await admin.put(f"{API}/v1/system/psk",
                        json={"channels": {channel: base64.b64encode(key).decode()}})
    assert r.status_code == 200, r.text

    try:
        data = _vi(1, 1) + _ld(2, text.encode())          # TEXT_MESSAGE_APP
        pkt_id = int(uuid.uuid4().hex[:12], 16)
        packet = (_vi(1, from_id) + _vi(2, 0xFFFFFFFF)
                  + _ld(5, _encrypt(key, from_id, pkt_id, data)) + _vi(6, pkt_id))
        envelope = (_ld(1, packet) + _ld(2, channel.encode()) + _ld(3, b"!testgate"))

        await publish_mqtt(f"msh/{zone}/2/e/{channel}/{node}", envelope,
                           mqtt_all["username"], mqtt_all["password"])

        deadline = time.time() + 15.0
        seen = None
        while time.time() < deadline and seen is None:
            r = await admin.get(f"{API}/v1/packets",
                                params={"topic": channel, "limit": 10})
            for p in (r.json().get("data") or []):
                if p.get("packet_type") == "meshtastic-text":
                    detail = (await admin.get(f"{API}/v1/packets/{p['id']}")).json()["data"]
                    # текстът живее в mesh.text (детайлът пре-декодира с PSK);
                    # payload_text е за JSON envelope-и, при бинарни е None
                    if (detail.get("mesh") or {}).get("text") == text                             or detail.get("payload_text") == text:
                        seen = detail
                        break
            if seen is None:
                await asyncio.sleep(0.5)
        assert seen is not None, "криптираният пакет не се декодира с PSK"
        assert seen["decoder_id"] == "meshtastic-protobuf+psk"
    finally:
        await admin.put(f"{API}/v1/system/psk", json={"channels": {channel: None}})
