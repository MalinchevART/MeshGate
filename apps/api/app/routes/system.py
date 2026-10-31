from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..security import CurrentUser, audit, require_admin, require_viewer

router = APIRouter(prefix="/v1/system", tags=["system"])


@router.post("/emulator/{action}")
async def emulator_control(action: str, request: Request,
                           user: CurrentUser = Depends(require_admin)):
    """Пауза/продължаване на демо емулатора (тестовите възли) през контролната
    тема mesh/emul/ctrl — емулаторът я слуша и спира/връща публикуването."""
    if action not in ("pause", "resume"):
        raise HTTPException(status_code=422, detail="действието е pause или resume")
    ingest = request.app.state.ingest
    if ingest._client is None:
        raise HTTPException(status_code=503, detail="приемникът не е свързан с брокера")
    await ingest.publish_local("mesh/emul/ctrl", action.encode(), "system:emulator")
    # Т37-пред: състоянието е ТРАЙНО — при рестарт на api паузата се прилага
    # отново (собственик, 30.10: тестовите възли спрени по подразбиране)
    paused = "true" if action == "pause" else "false"
    await request.app.state.pool.execute(
        "INSERT INTO settings (key, value) VALUES ('emulator_paused', $1::jsonb)"
        " ON CONFLICT (key) DO UPDATE SET value = $1::jsonb",
        paused)
    await audit(request.app.state.pool, user, "system.emulator", "emulator", None,
                {"action": action})
    return {"data": {"action": action}}


@router.get("/health")
async def health(request: Request):
    state = request.app.state
    components = {}
    try:
        await state.pool.fetchval("SELECT 1")
        components["postgres"] = "ok"
    except Exception:
        components["postgres"] = "down"
    try:
        await state.adapter.status()
        components["broker"] = "ok"
    except Exception:
        components["broker"] = "down"
    components["ingestion"] = "ok" if state.ingest.healthy else "down"
    components["bridge"] = "ok" if state.bridge.healthy() else "down"
    overall = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return {"data": {"status": overall, "components": components}}


@router.get("/status")
async def status(request: Request):
    state = request.app.state
    broker = None
    try:
        broker = await state.adapter.status()
    except Exception:
        pass
    packets_count = await state.pool.fetchval("SELECT count(*) FROM packets")
    devices_count = await state.pool.fetchval("SELECT count(*) FROM devices")
    return {
        "data": {
            "app": "meshgate",
            "phase": "0-mvp",
            "broker": broker,
            "packets_total": packets_count,
            "devices_total": devices_count,
            "bridges": state.bridge.summary(),
        }
    }


# ---------- Т36 срез 2 (ADR-007): PSK ключове по канал -----------------------

@router.get("/psk")
async def get_psk(request: Request, user: CurrentUser = Depends(require_admin)):
    """Списък на каналите с въведен ключ — БЕЗ самите ключове (само
    форма/дължина, за да личи какво е въведено). Стойностите не се показват."""
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT value FROM settings WHERE key='psk'")
    cfg: dict = {}
    if row is not None:
        import json as _json
        try:
            cfg = _json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
        except (ValueError, TypeError):
            cfg = {}
    channels = {
        ch: {"length": len(v or ""), "one_byte": isinstance(v, str) and len(v) <= 8}
        for ch, v in (cfg or {}).items() if isinstance(ch, str)
    }
    return {"data": {"channels": channels}}


class PskIn(BaseModel):
    channels: dict[str, str | None]


@router.put("/psk")
async def put_psk(body: PskIn, request: Request,
                  user: CurrentUser = Depends(require_admin)):
    """Запис на PSK ключове по канал (base64; празно/None = премахни).
    Влизат в сила НА ЖИВО (ingest презарежда картата без рестарт).
    Стойностите не се връщат в отговора и не се логват."""
    import json as _json
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT value FROM settings WHERE key='psk'")
    cfg: dict = {}
    if row is not None:
        try:
            cfg = _json.loads(row["value"]) if isinstance(row["value"], str) else dict(row["value"])
        except (ValueError, TypeError):
            cfg = {}
    for ch, v in body.channels.items():
        if v is None or not v.strip():
            cfg.pop(ch, None)
        else:
            cfg[ch] = v.strip()
    await pool.execute(
        "INSERT INTO settings (key, value) VALUES ('psk', $1::jsonb)"
        " ON CONFLICT (key) DO UPDATE SET value = $1::jsonb",
        _json.dumps(cfg))
    ingest = getattr(request.app.state, "ingest", None)
    if ingest is not None:
        await ingest.load_psk_map(cfg)
    await audit(pool, user, "system.psk", "settings", "psk",
                {"channels": sorted(cfg.keys())})
    return {"data": {"channels": sorted(cfg.keys())}}


# ---------- Т35 (ADR-008): геозони ------------------------------------------

@router.get("/geofence")
async def get_geofence(request: Request, user: CurrentUser = Depends(require_viewer)):
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT value FROM settings WHERE key='geofence'")
    zones: list = []
    if row is not None:
        import json as _json
        try:
            zones = _json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
        except (ValueError, TypeError):
            zones = []
    return {"data": {"zones": zones or []}}


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    node: str = "*"
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, le=100_000)


class ZonesIn(BaseModel):
    zones: list[ZoneIn]


@router.put("/geofence")
async def put_geofence(body: ZonesIn, request: Request,
                       user: CurrentUser = Depends(require_admin)):
    """Записва целия списък зони; детекторът ги взема при следващия цикъл
    (evaluator-ът чете settings на всеки цикъл — без рестарт)."""
    import json as _json
    pool = request.app.state.pool
    zones = [z.model_dump() for z in body.zones]
    await pool.execute(
        "INSERT INTO settings (key, value) VALUES ('geofence', $1::jsonb)"
        " ON CONFLICT (key) DO UPDATE SET value = $1::jsonb",
        _json.dumps(zones))
    await audit(pool, user, "system.geofence", "settings", "geofence",
                {"zones": len(zones)})
    return {"data": {"zones": zones}}
