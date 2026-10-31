"""Т8 интеграционен тест: /v1/dashboard — форма, нули, консистентност с
съществуващите endpoints (консистентност ПО КОНСТРУКЦИЯ се заключва тук)."""
import httpx
import pytest

from conftest import ITEST, ensure_itest_admin
from test_checklist import API, login


@pytest.fixture
async def admin():
    await ensure_itest_admin()
    async with httpx.AsyncClient() as c:
        await login(c, ITEST)
        yield c


async def test_dashboard_shape_and_zero_fill(admin):
    r = await admin.get(f"{API}/v1/dashboard?hours=24")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["hours"] == 24
    # трафик: hours+1 почасови кофи, всяка с count >= 0
    assert len(d["traffic"]) == 25
    assert all(b["count"] >= 0 for b in d["traffic"])
    # изпратени: ТОЧНО 8 кофи по 3ч
    assert len(d["sent_24h"]) == 8
    assert all(b["sent"] >= 0 and b["failed"] >= 0 for b in d["sent_24h"])
    # KPI прозорците са самописващи се
    assert d["kpi"]["windows"]["alarms"] == 24
    assert d["kpi"]["windows"]["nodes"] == 24
    # канали: име + брой, най-много 12
    assert len(d["channels"]) <= 12
    assert all(c["name"] and c["count"] >= 0 for c in d["channels"])
    # производни на кофите
    assert d["kpi"]["packets"]["total"] == sum(b["count"] for b in d["traffic"])


async def test_dashboard_hours_clamped(admin):
    r = await admin.get(f"{API}/v1/dashboard?hours=99999")
    assert r.status_code == 200
    assert r.json()["data"]["hours"] == 168
    r = await admin.get(f"{API}/v1/dashboard?hours=0")
    assert r.status_code == 200
    assert r.json()["data"]["hours"] == 1


async def test_dashboard_consistency_with_existing(admin):
    """Тъждествата от дизайна: трафик == stats/overview; аларми ==
    critical counts; RF == topology edges. Текущата (непълна) кофа се
    изключва — между двете заявки идват живи пакети и това не е разминаване;
    алармите толерират ≤2 (evaluator цикъл 2s в тестов профил)."""
    d = (await admin.get(f"{API}/v1/dashboard?hours=24")).json()["data"]
    s = (await admin.get(f"{API}/v1/stats/overview?hours=24")).json()["data"]
    db = {b["hour"]: b["count"] for b in d["traffic"][:-1]}
    sb = {b["hour"]: b["count"] for b in s["buckets"][:-1]}
    assert db == sb, "кофите на дашборда и stats/overview се разминават"

    c = (await admin.get(f"{API}/v1/critical-events?hours=24")).json()["data"]["counts"]
    assert abs(d["kpi"]["alarms"]["open"] - c["open"]) <= 2, \
        "алармите се разминават с критичните събития"

    t = (await admin.get(f"{API}/v1/devices/topology?hours=24")).json()["data"]
    assert d["kpi"]["rf"]["links"] == len(t["edges"])
    assert d["kpi"]["rf"]["nodes"] == t["nodes"]


async def test_dashboard_rbac():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{API}/v1/dashboard")
        assert r.status_code == 401
