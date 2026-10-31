"""Мета-интерфейсът: план (кое кога), selftest и статистики за мониторинга."""

import httpx
import pytest

from conftest import ITEST as ADMIN, ensure_itest_admin
from test_checklist import API, login


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ADMIN)
        yield c


async def test_anomalies_endpoint(admin):
    """/v1/anomalies: случилите се събития върху оста на времето."""
    r = (await admin.get(f"{API}/v1/anomalies?hours=24")).json()["data"]
    assert r["hours"] == 24 and isinstance(r["events"], list)
    for e in r["events"][:10]:
        assert e["ts"] and e["label"] and e["kind"]
    # живият стек почти винаги има rule_publish (демо правилата се publish-ваха)
    kinds = {e["kind"] for e in r["events"]}
    assert "rule_publish" in kinds or not r["events"], kinds


async def test_plan_and_selftest(admin):
    r = await admin.get(f"{API}/v1/plan")
    assert r.status_code == 200
    plan = r.json()["data"]
    assert plan["phases"], "празен план"
    statuses = {p["status"] for p in plan["phases"]}
    # винаги има завършено и предстоящо; активната фаза може да е active или next
    assert "done" in statuses and "later" in statuses
    assert statuses & {"active", "next"}
    assert all(p["status"] in ("done", "active", "next", "later") for p in plan["phases"])
    for p in plan["phases"]:
        assert p["title"] and p["when"], p
        for it in p["items"]:
            assert it["title"]

    r = await admin.get(f"{API}/v1/selftest")
    assert r.status_code == 200
    data = r.json()["data"]
    ids = {c["id"] for c in data["auto"]}
    assert {"db", "broker", "ingest", "traffic", "routing", "bridges", "password"} <= ids
    assert all(c["status"] in ("ok", "warn", "fail") for c in data["auto"])
    # жив стек: db и ingest трябва да са ok
    by_id = {c["id"]: c for c in data["auto"]}
    assert by_id["db"]["status"] == "ok"
    assert by_id["ingest"]["status"] == "ok"
    # ръчният чеклист присъства
    assert len(data["manual"]) >= 6
    assert all(m["steps"] and m["expected"] for m in data["manual"])


async def test_stats_overview(admin):
    r = await admin.get(f"{API}/v1/stats/overview?hours=24")
    assert r.status_code == 200
    data = r.json()["data"]
    # 25 buckets (24 часа + текущия), наляво с нули
    assert len(data["buckets"]) == 25
    assert sum(b["count"] for b in data["buckets"]) > 0  # има трафик (emulator)
    assert data["families"], "няма групирани канали"
    # емулаторски mesh/ ИЛИ реален Meshtastic трафик от входящ мост (msh/) —
    # топ-12 може да се доминира от жив публичен мост
    assert any(
        f["family"].startswith(("mesh/", "msh/")) for f in data["families"]
    ), [f["family"] for f in data["families"]]
    # батерии от emulator телеметрия (или от реален protobuf decode)
    assert data["batteries"] and all(
        isinstance(b["battery"], (int, float)) for b in data["batteries"]
    )
    assert isinstance(data["rules"], list)
