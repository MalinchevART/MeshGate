"""Home Assistant интеграция на жив стек (docs/13 §1): включване →
discovery конфиг + състояния; homeassistant/ темите не се записват."""
import asyncio
import json
import time
import uuid

import httpx

from conftest import ITEST as ADMIN, ensure_itest_admin
from test_checklist import API, login, publish_mqtt


async def _packet_seen(admin, substr: str, timeout_s: float = 12.0) -> list[dict]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = await admin.get(f"{API}/v1/packets", params={"topic": substr, "limit": 10})
        rows = r.json().get("data") or []
        if rows:
            return rows
        await asyncio.sleep(0.4)
    return []


async def test_home_assistant_end_to_end():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as admin:
        await login(admin, ADMIN)

        username = f"ha-{uuid.uuid4().hex[:8]}"
        r = await admin.post(f"{API}/v1/broker/credentials",
                             json={"username": username, "topics": ["#"]})
        assert r.status_code == 201, r.text
        pw = r.json()["data"]["password"]
        try:
            # изключен по подразбиране (или от предишен тест) → включваме
            assert (await admin.post(f"{API}/v1/home-assistant/enable")).status_code == 200
            st = (await admin.get(f"{API}/v1/home-assistant")).json()["data"]
            assert st["enabled"] is True

            # публикуваме телеметрия от възел → адаптерът праща discovery + state
            node = f"!{uuid.uuid4().hex[:8]}"
            env = json.dumps({
                "id": int(time.time() * 1000) % 0xFFFF, "to": -1,
                "from": int(node[1:], 16), "sender": node, "channel": 0,
                "decoded": {"portnum": "TELEMETRY_APP",
                            "telemetry": {"device_metrics": {"battery_level": 42}}},
            })
            await publish_mqtt(f"msh/emul/2/e/LongFast/{node}", env, username, pw)

            states = await _packet_seen(admin, f"meshgate/{node}/battery")
            assert states, "състоянието на батерията не се появи"
            det = (await admin.get(f"{API}/v1/packets/{states[0]['id']}")).json()["data"]
            assert det["payload_text"] == "42", det["payload_text"]

            # discovery конфигите НЕ се записват (skip на homeassistant/)
            await asyncio.sleep(1.5)
            r = await admin.get(f"{API}/v1/packets",
                                params={"topic": "homeassistant/", "limit": 10})
            assert not (r.json().get("data") or []), "discovery темите не бива да се записват"

            # статусът брои възела
            st2 = (await admin.get(f"{API}/v1/home-assistant")).json()["data"]
            assert st2["nodes"] >= 1
            assert any(n["node"] == node for n in st2["node_list"])

            # тестовият възел работи
            r = await admin.post(f"{API}/v1/home-assistant/test")
            assert r.status_code == 200, r.text
            assert await _packet_seen(admin, "meshgate/!test1234/battery")

            # изключване
            assert (await admin.post(f"{API}/v1/home-assistant/disable")).status_code == 200
            st3 = (await admin.get(f"{API}/v1/home-assistant")).json()["data"]
            assert st3["enabled"] is False
        finally:
            rows = (await admin.get(f"{API}/v1/broker/credentials")).json()["data"]
            for row in rows:
                if row["username"] == username:
                    await admin.delete(f"{API}/v1/broker/credentials/{row['id']}")
