import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..broker.adapter import BrokerUnavailable
from ..security import CurrentUser, audit, require_admin, require_operator, require_viewer

router = APIRouter(prefix="/v1/broker", tags=["broker"])


@router.get("/status")
async def broker_status(request: Request, user: CurrentUser = Depends(require_viewer)):
    try:
        return {"data": await request.app.state.adapter.status()}
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"broker_unavailable: {exc}")


@router.get("/clients")
async def clients(request: Request, user: CurrentUser = Depends(require_viewer)):
    rows = await request.app.state.adapter.clients()
    return {
        "data": [
            {
                "client_id": c.get("clientid"),
                "username": c.get("username"),
                "ip": c.get("ip_address"),
                "connected": c.get("connected"),
                "connected_at": c.get("connected_at"),
                "subscriptions_count": c.get("subscriptions_cnt"),
            }
            for c in rows
        ]
    }


@router.get("/subscriptions")
async def subscriptions(request: Request, user: CurrentUser = Depends(require_viewer)):
    rows = await request.app.state.adapter.subscriptions()
    return {
        "data": [
            {
                "client_id": s.get("clientid"),
                "topic": s.get("topic"),
                "qos": s.get("qos"),
            }
            for s in rows
        ]
    }


@router.delete("/clients/{client_id}")
async def kick_client(
    client_id: str, request: Request, user: CurrentUser = Depends(require_operator)
):
    await request.app.state.adapter.kick_client(client_id)
    await audit(request.app.state.pool, user, "broker.kick_client", "client", client_id)
    return {"data": {"ok": True}}


class TestPublishIn(BaseModel):
    topic: str
    payload: str
    qos: int = 0


@router.post("/test-publish")
async def test_publish(
    body: TestPublishIn, request: Request, user: CurrentUser = Depends(require_operator)
):
    await request.app.state.adapter.publish(body.topic, body.payload, body.qos)
    await audit(
        request.app.state.pool,
        user,
        "broker.test_publish",
        "topic",
        body.topic,
        {"qos": body.qos, "size": len(body.payload)},
    )
    return {"data": {"ok": True}}


class CredentialIn(BaseModel):
    username: str
    topics: list[str]


@router.get("/credentials")
async def list_credentials(request: Request, user: CurrentUser = Depends(require_admin)):
    rows = await request.app.state.pool.fetch(
        "SELECT id, username, allowed_topics, created_at FROM mqtt_credentials ORDER BY created_at DESC"
    )
    return {
        "data": [
            {
                "id": str(r["id"]),
                "username": r["username"],
                "allowed_topics": r["allowed_topics"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/credentials", status_code=201)
async def create_credential(
    body: CredentialIn, request: Request, user: CurrentUser = Depends(require_admin)
):
    password = secrets.token_urlsafe(16)
    adapter = request.app.state.adapter
    try:
        await adapter.create_mqtt_user(body.username, password)
        await adapter.set_acl_rules(body.username, body.topics, action="all")
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"broker_unavailable: {exc}")
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "INSERT INTO mqtt_credentials (username, allowed_topics) VALUES ($1, $2::jsonb)"
        " RETURNING id",
        body.username,
        __import__("json").dumps(body.topics),
    )
    await audit(
        pool,
        user,
        "broker.credential_create",
        "mqtt_user",
        body.username,
        {"topics": body.topics},
    )
    return {"data": {"id": str(row["id"]), "username": body.username, "password": password}}


@router.delete("/credentials/{cred_id}")
async def delete_credential(
    cred_id: str, request: Request, user: CurrentUser = Depends(require_admin)
):
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "DELETE FROM mqtt_credentials WHERE id = $1 RETURNING username", cred_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    adapter = request.app.state.adapter
    try:
        await adapter.drop_acl_rules(row["username"])
    except BrokerUnavailable:
        pass
    try:
        await adapter.delete_mqtt_user(row["username"])
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"broker_unavailable: {exc}")
    await audit(pool, user, "broker.credential_delete", "mqtt_user", row["username"])
    return {"data": {"ok": True}}
