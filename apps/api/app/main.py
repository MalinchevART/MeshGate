# MeshGate platform core.
# Built by the N&M Control team.

import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import db, security
from .bridge.engine import BridgeEngine
from .broker.adapter import EmqxAdapter
from .config import settings
from .critical import CriticalEngine
from .ingest.service import IngestService
from .integrations.ha_engine import HomeAssistantEngine
from .notify.engine import NotificationEngine
from .routing.service import RoutingEngine
from .routes import audit, auth, broker, bridges, critical, dashboard, devices, gateways, ha, integration, meta, notifications, packets, profiles, routing, system, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("meshgate")

RETENTION_INTERVAL_S = 6 * 3600


async def bootstrap_admin(pool) -> None:
    count = await pool.fetchval("SELECT count(*) FROM users")
    if count:
        return
    s = settings()
    await pool.execute(
        "INSERT INTO users (username, password_hash, role) VALUES ($1,$2,'admin')",
        s.meshgate_admin_user,
        security.hash_password(s.meshgate_admin_password),
    )
    if s.meshgate_admin_password == security.DEFAULT_ADMIN_PASSWORD:
        log.warning(
            "bootstrap: администраторът '%s' е създаден с НАЧАЛНА парола — "
            "UI и meshgate.cmd ще предлагат смяна",
            s.meshgate_admin_user,
        )


async def ensure_emulator_device(pool, adapter) -> None:
    """Идемпотентна подготовка на демо емулатора: MQTT потребител с ACL само
    върху mesh/emul/#. Преконструира го при всеки старт (евтино, един потребител),
    за да оцелява след wipe на EMQX тома (напр. след e2e)."""
    s = settings()
    if not s.meshgate_emulator_user or not s.meshgate_emulator_password:
        return
    try:
        await adapter.delete_mqtt_user(s.meshgate_emulator_user)
        await adapter.create_mqtt_user(s.meshgate_emulator_user, s.meshgate_emulator_password)
        await adapter.drop_acl_rules(s.meshgate_emulator_user)
        # v2 емулаторът публикува и в msh/# (Meshtastic-режим), и в mesh/emul/#
        topics = ["mesh/emul/#", "msh/#"]
        await adapter.set_acl_rules(s.meshgate_emulator_user, topics)
        await pool.execute(
            "INSERT INTO mqtt_credentials (username, allowed_topics)"
            " VALUES ($1, $2::jsonb)"
            " ON CONFLICT (username) DO UPDATE SET allowed_topics = $2::jsonb",
            s.meshgate_emulator_user,
            json.dumps(topics),
        )
        log.info("bootstrap: демо емулаторът '%s' е готов", s.meshgate_emulator_user)
    except Exception:
        log.warning(
            "bootstrap: емулаторният потребител не е подготвен (брокерът е недостъпен?); "
            "нов опит при следващ старт"
        )


async def seed_profiles(pool) -> None:
    from .routes.profiles import FACTORY_PROFILES

    for name, meta in FACTORY_PROFILES.items():
        pid = await pool.fetchval(
            "INSERT INTO profiles (name, description) VALUES ($1,$2)"
            " ON CONFLICT (name) DO UPDATE SET description=$2 RETURNING id",
            name,
            meta["description"],
        )
        await pool.execute(
            "INSERT INTO profile_versions (profile_id, version, spec) VALUES ($1, 1, $2::jsonb)"
            " ON CONFLICT (profile_id, version) DO NOTHING",
            pid,
            json.dumps(meta["spec"]),
        )


async def retention_loop(pool) -> None:
    while True:
        try:
            raw_days = int(
                (
                    await pool.fetchval(
                        "SELECT value->>'packets_raw_days' FROM settings WHERE key='retention'"
                    )
                )
                or settings().retention_packets_raw
            )
            events_days = int(
                (
                    await pool.fetchval(
                        "SELECT value->>'events_days' FROM settings WHERE key='retention'"
                    )
                )
                or settings().retention_events
            )
            n1 = await pool.execute(
                "UPDATE packets SET payload_raw = NULL"
                " WHERE payload_raw IS NOT NULL AND ts < now() - make_interval(days => $1)",
                raw_days,
            )
            n2 = await pool.execute(
                "DELETE FROM events WHERE ts < now() - make_interval(days => $1)",
                events_days,
            )
            log.info("retention: пакети-суровини изчистени %s, събития %s", n1, n2)
        except Exception:
            log.exception("retention: грешка")
        await asyncio.sleep(RETENTION_INTERVAL_S)


async def _reapply_emulator_pause(pool, ingest) -> None:
    """Т37-пред: ако демо емулаторът е бил паузиран (settings), прилага паузата
    щом ingest поеме връзката — тестовите възли остават спрени през рестарти."""
    for _ in range(60):  # до ~5 мин чакане на връзката
        if ingest.healthy:
            break
        await asyncio.sleep(5)
    row = await pool.fetchrow(
        "SELECT value FROM settings WHERE key = 'emulator_paused'")
    if row is None:
        return
    try:
        v = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
    except (json.JSONDecodeError, TypeError):
        return
    if v is True or v == "true":
        try:
            await ingest.publish_local("mesh/emul/ctrl", b"pause", "system:emulator")
            log.info("emulator: паузата възстановена след рестарт")
        except Exception as exc:
            log.warning("emulator: паузата не се приложи (%s)", exc)


async def lifespan(app: FastAPI):
    pool = await db.connect()
    applied = await db.migrate(pool)
    if applied:
        log.info("миграции: %s", ", ".join(applied))
    await bootstrap_admin(pool)
    await seed_profiles(pool)

    adapter = EmqxAdapter()
    await ensure_emulator_device(pool, adapter)
    bridge = BridgeEngine(pool)
    await bridge.load()
    routing = RoutingEngine(pool, bridge)
    await routing.load()
    notify = NotificationEngine(pool)
    await notify.load()
    notify.start()
    ha = HomeAssistantEngine(pool)
    await ha.load()
    ha.start()
    critical_engine = CriticalEngine(pool)
    critical_engine.start()
    ingest = IngestService(pool, bridge)
    # кръстосано свързване: routing публикува локално през ingest клиента,
    # ingest подава всяко локално съобщение на routing engine-а
    routing.ingest = ingest
    ingest.routing = routing
    ingest.notify = notify
    ingest.ha = ha
    ha.ingest = ingest

    await ingest.load_psk_map()  # Т36 срез 2: PSK ключовете от settings
    app.state.pool = pool
    app.state.adapter = adapter
    app.state.bridge = bridge
    app.state.ingest = ingest
    app.state.routing = routing
    app.state.notify = notify
    app.state.ha = ha
    app.state.critical = critical_engine

    tasks = [
        asyncio.create_task(ingest.run(), name="ingest"),
        asyncio.create_task(retention_loop(pool), name="retention"),
        asyncio.create_task(_reapply_emulator_pause(pool, ingest), name="emulator-pause"),
    ]
    log.info("MeshGate API стартиран")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await critical_engine.stop()
        await notify.stop()
        await ha.stop()
        await routing.stop()
        await bridge.stop()
        await adapter.close()
        await pool.close()


app = FastAPI(title="MeshGate API", version="0.1.0", lifespan=lifespan)

# пулс/facets отговорите са повторяем JSON с hundreds обекти — gzip ги
# сваля ~10x (полинга на всеки 60s става безшумен)
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(auth.router)
app.include_router(system.router)
app.include_router(broker.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(packets.router)
app.include_router(bridges.router)
app.include_router(routing.router)
app.include_router(notifications.router)
app.include_router(critical.router)
app.include_router(dashboard.router)
app.include_router(gateways.router)
app.include_router(meta.router)
app.include_router(profiles.router)
app.include_router(audit.router)
app.include_router(integration.router)
app.include_router(ha.router)


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.detail), "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request: Request, exc: RequestValidationError):
    # exc.errors() носи суровите входни стойности — NaN/Infinity чупят
    # JSON сериализацията (json.dumps allow_nan=False) и превръщат 422 в 500;
    # режем ги до низ + изключваме не-JSON частите от ctx
    def _safe(v):
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            return str(v)
        if isinstance(v, (bytes, bytearray)):
            return v.decode("utf-8", "replace")[:200]
        if isinstance(v, dict):
            return {k: _safe(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_safe(x) for x in v]
        return v

    details = [
        {k: _safe(v) for k, v in e.items() if k != "ctx"} for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_failed",
                "message": "невалидни данни",
                "details": details,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    log.exception("необработена грешка")
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "вътрешна грешка"}},
    )
