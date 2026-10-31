"""Модул за външна интеграция: MeshGate се включва в по-голям мрежов проект
(напр. централен NMS) чрез API токен + REST + live поток + контролиран publish.
Контрактът е документиран в docs/08-external-integration.md."""

import asyncio
import hashlib
import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..broker.adapter import BrokerUnavailable
from ..bridge.rules import mqtt_match
from ..bus import bus
from ..security import CurrentUser, audit, require_admin

router = APIRouter(prefix="/v1/integration", tags=["integration"])


class TokenPrincipal:
    def __init__(self, row_id: str, name: str, can_publish: bool, allowed_topics: list[str]):
        self.id = row_id
        self.name = name
        self.can_publish = can_publish
        self.allowed_topics = allowed_topics


async def _resolve_token(request: Request) -> TokenPrincipal | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ").strip()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = await request.app.state.pool.fetchrow(
        "SELECT id, name, can_publish, allowed_topics FROM api_tokens WHERE token_hash = $1",
        token_hash,
    )
    if not row:
        return None
    return TokenPrincipal(str(row["id"]), row["name"], row["can_publish"], json.loads(row["allowed_topics"]))


def require_token(request: Request) -> TokenPrincipal:
    # синхронен вид, но се вика само от async маршрути с await _resolve_token
    raise HTTPException(status_code=401, detail="unauthorized")


class TokenIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    can_publish: bool = False
    allowed_topics: list[str] = Field(default_factory=list)


# --- управление на токените (само admin, сесия) ---

@router.get("/tokens")
async def list_tokens(request: Request, user: CurrentUser = Depends(require_admin)):
    rows = await request.app.state.pool.fetch(
        "SELECT id, name, can_publish, allowed_topics, created_at FROM api_tokens ORDER BY created_at"
    )
    return {
        "data": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "can_publish": r["can_publish"],
                "allowed_topics": r["allowed_topics"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/tokens", status_code=201)
async def create_token(body: TokenIn, request: Request, user: CurrentUser = Depends(require_admin)):
    if body.can_publish and not body.allowed_topics:
        raise HTTPException(
            status_code=422,
            detail="validation_failed: токен с publish изисква allowed_topics",
        )
    token = "mg_" + secrets.token_urlsafe(32)
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "INSERT INTO api_tokens (name, token_hash, can_publish, allowed_topics)"
        " VALUES ($1,$2,$3,$4::jsonb) RETURNING id",
        body.name,
        hashlib.sha256(token.encode()).hexdigest(),
        body.can_publish,
        json.dumps(body.allowed_topics),
    )
    await audit(pool, user, "integration.token_create", "token", body.name,
                {"can_publish": body.can_publish, "topics": body.allowed_topics})
    return {"data": {"id": str(row["id"]), "name": body.name, "token": token}}


@router.delete("/tokens/{token_id}")
async def delete_token(token_id: str, request: Request, user: CurrentUser = Depends(require_admin)):
    pool = request.app.state.pool
    name = await pool.fetchval("DELETE FROM api_tokens WHERE id=$1 RETURNING name", token_id)
    if not name:
        raise HTTPException(status_code=404, detail="not_found")
    await audit(pool, user, "integration.token_delete", "token", name)
    return {"data": {"ok": True}}


# --- външен API (Bearer токен) ---

@router.get("/status")
async def integration_status(request: Request):
    principal = await _resolve_token(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    state = request.app.state
    try:
        broker = await state.adapter.status()
    except BrokerUnavailable:
        broker = None
    return {
        "data": {
            "app": "meshgate",
            "token_name": principal.name,
            "broker": broker,
            "bridges": state.bridge.summary(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    }


@router.get("/devices")
async def integration_devices(request: Request, limit: int = 100):
    principal = await _resolve_token(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    limit = min(limit, 200)
    rows = await request.app.state.pool.fetch(
        "SELECT external_id, protocol, status, last_seen_at FROM devices"
        " ORDER BY last_seen_at DESC LIMIT $1",
        limit,
    )
    return {
        "data": [
            {
                "external_id": r["external_id"],
                "protocol": r["protocol"],
                "status": r["status"],
                "last_seen_at": r["last_seen_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/packets")
async def integration_packets(
    request: Request,
    topic: str | None = None,
    limit: int = 50,
    before: str | None = None,
):
    principal = await _resolve_token(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    limit = min(limit, 200)
    where = ["TRUE"]
    args: list = []
    if topic:
        args.append(f"%{topic}%")
        where.append(f"topic LIKE ${len(args)}")
    if before:
        args.append(before)
        where.append(f"ts < ${len(args)}")
    args.append(limit)
    rows = await request.app.state.pool.fetch(
        f"SELECT ts, topic, packet_type, decode_status, payload_size FROM packets"
        f" WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ${len(args)}",
        *args,
    )
    return {
        "data": [
            {
                "ts": r["ts"].isoformat(),
                "topic": r["topic"],
                "packet_type": r["packet_type"],
                "decode_status": r["decode_status"],
                "payload_size": r["payload_size"],
            }
            for r in rows
        ]
    }


class IntegrationPublishIn(BaseModel):
    topic: str
    payload: str


@router.post("/publish")
async def integration_publish(body: IntegrationPublishIn, request: Request):
    principal = await _resolve_token(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not principal.can_publish:
        raise HTTPException(status_code=403, detail="forbidden: токенът няма publish")
    if not any(mqtt_match(pat, body.topic) for pat in principal.allowed_topics):
        raise HTTPException(
            status_code=403,
            detail=f"forbidden: темата не е в allowed_topics на токена",
        )
    try:
        await request.app.state.adapter.publish(body.topic, body.payload)
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"broker_unavailable: {exc}")
    await audit(
        request.app.state.pool,
        None,
        "integration.publish",
        "token",
        principal.name,
        {"topic": body.topic, "size": len(body.payload)},
    )
    return {"data": {"ok": True}}


@router.websocket("/ws/packets")
async def integration_ws(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = await websocket.app.state.pool.fetchrow(
        "SELECT name FROM api_tokens WHERE token_hash = $1", token_hash
    )
    if not row:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    topic_contains = websocket.query_params.get("topic") or None
    q = bus.subscribe()
    try:
        while True:
            get_task = asyncio.create_task(q.get())
            hb_task = asyncio.create_task(asyncio.sleep(15))
            done, pending = await asyncio.wait(
                {get_task, hb_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            if hb_task in done:
                await websocket.send_json({"type": "heartbeat"})
                continue
            event = get_task.result()
            data = event.get("data", {})
            if topic_contains and topic_contains not in data.get("topic", ""):
                continue
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)
