"""Home Assistant интеграция (docs/13 §1): статус, вкл/изкл, тестов сензор."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request

from ..security import CurrentUser, audit, require_admin, require_viewer

router = APIRouter(prefix="/v1/home-assistant", tags=["home-assistant"])


@router.get("")
async def ha_status(request: Request, user: CurrentUser = Depends(require_viewer)):
    ha = request.app.state.ha
    counts = ha.counters()
    nodes = sorted(ha.entities.items(), key=lambda kv: -len(kv[1]))[:50]
    return {
        "data": {
            **counts,
            "node_list": [
                {"node": n, "entities": ents} for n, ents in nodes
            ],
        }
    }


async def _set_enabled(request: Request, enabled: bool, user) -> dict:
    pool = request.app.state.pool
    await pool.execute(
        "INSERT INTO settings (key, value) VALUES ('homeassistant', $1::jsonb)"
        " ON CONFLICT (key) DO UPDATE SET value = $1::jsonb",
        json.dumps({"enabled": enabled}),
    )
    ha = request.app.state.ha
    ha.enabled = enabled
    await audit(pool, user, "integration.homeassistant", "settings",
                f"homeassistant={'on' if enabled else 'off'}")
    # СЪЩИЯ shape като GET статуса — фронтендът сменя състоянието на място
    counts = ha.counters()
    nodes = sorted(ha.entities.items(), key=lambda kv: -len(kv[1]))[:50]
    return {
        "data": {
            **counts,
            "node_list": [{"node": n, "entities": ents} for n, ents in nodes],
        }
    }


@router.post("/enable")
async def ha_enable(request: Request, user: CurrentUser = Depends(require_admin)):
    return await _set_enabled(request, True, user)


@router.post("/disable")
async def ha_disable(request: Request, user: CurrentUser = Depends(require_admin)):
    return await _set_enabled(request, False, user)


@router.post("/test")
async def ha_test(request: Request, user: CurrentUser = Depends(require_admin)):
    """Публикува тестов възел !test1234 — ако HA е закачен, сензорите се
    появяват веднага (батерия 99% + съобщение)."""
    ha = request.app.state.ha
    if ha.ingest is None:
        raise HTTPException(status_code=503, detail="адаптерът още не е свързан с брокера")
    node = await ha.publish_test()
    await audit(request.app.state.pool, user, "integration.homeassistant_test",
                "settings", node)
    return {"data": {"test_node": node}}
