import ipaddress
import json
import socket

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..security import CurrentUser, audit, require_admin, require_viewer

router = APIRouter(prefix="/v1/bridges", tags=["bridges"])


class RuleIn(BaseModel):
    kind: str = Field(pattern=r"^(allow|deny)$")
    topic_pattern: str = Field(min_length=1, max_length=256)
    payload_type: str | None = None
    priority: int = 100
    reason: str | None = None


class BridgeIn(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    direction: str = Field(default="outbound", pattern=r"^(inbound|outbound|bidirectional)$")
    remote_host: str = Field(min_length=1, max_length=253)
    remote_username: str | None = Field(default=None, max_length=128)
    remote_password: str | None = Field(default=None, max_length=128)
    remote_port: int = Field(ge=1, le=65535, default=1883)
    allow_internal: bool = False
    topic_map: list[dict] = Field(default_factory=list)
    rate_limit_per_min: int = Field(ge=1, le=100000, default=60)
    rules: list[RuleIn]


# Документационни диапазони (RFC 5737/3849) — недостижими по дизайн; позволяваме
# ги, за да могат тестовете да симулират недостиж external broker.
TEST_NETS = [
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("2001:db8::/32"),
]


def validate_remote_host(host: str, allow_internal: bool, resolver=socket.getaddrinfo) -> None:
    """SSRF защита: резолвваме и блокираме частни/loopback/link-local адреси,
    освен при изричен allow_internal (вътрешни тестови цели)."""
    if host.lower() in ("localhost", "localhost.localdomain") and not allow_internal:
        raise HTTPException(status_code=422, detail="ssrf_blocked: localhost")
    try:
        infos = resolver(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=422, detail=f"ssrf_blocked: несъществуващ хост {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # Python брои TEST-NET диапазоните за "private" — ние ги допускаме
        in_test_net = any(ip in net for net in TEST_NETS)
        blocked = not in_test_net and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        )
        if blocked and not allow_internal:
            raise HTTPException(
                status_code=422,
                detail=f"ssrf_blocked: {host} се резолвва до вътрешен адрес {ip}",
            )


async def _bridge_out(pool, bridge_id: str) -> dict:
    r = await pool.fetchrow("SELECT * FROM bridge_configs WHERE id = $1", bridge_id)
    if not r:
        raise HTTPException(status_code=404, detail="not_found")
    rules = await pool.fetch(
        "SELECT kind, topic_pattern, payload_type, priority, reason FROM bridge_rules"
        " WHERE bridge_id = $1 ORDER BY priority",
        bridge_id,
    )
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "enabled": r["enabled"],
        "direction": r["direction"],
        "remote_host": r["remote_host"],
        "remote_port": r["remote_port"],
        "remote_username": r["remote_username"],
        "has_password": r["remote_password"] is not None,
        "allow_internal": r["allow_internal"],
        "tls_mode": r["tls_mode"],
        "topic_map": json.loads(r["topic_map"]),
        "rate_limit_per_min": r["rate_limit_per_min"],
        "health": r["health"],
        "last_error": r["last_error"],
        "rules": [
            {
                "kind": x["kind"],
                "topic_pattern": x["topic_pattern"],
                "payload_type": x["payload_type"],
                "priority": x["priority"],
                "reason": x["reason"],
            }
            for x in rules
        ],
    }


@router.get("")
async def list_bridges(request: Request, user: CurrentUser = Depends(require_viewer)):
    pool = request.app.state.pool
    rows = await pool.fetch("SELECT id FROM bridge_configs ORDER BY created_at")
    engine_state = {b["id"]: b for b in request.app.state.bridge.summary()}
    out = []
    for r in rows:
        b = await _bridge_out(pool, str(r["id"]))
        b["counters"] = engine_state.get(b["id"], {}).get("counters")
        if b["id"] in engine_state:
            b["health"] = engine_state[b["id"]]["health"]
        out.append(b)
    return {"data": out}


@router.post("", status_code=201)
async def create_bridge(body: BridgeIn, request: Request, user: CurrentUser = Depends(require_admin)):
    validate_remote_host(body.remote_host, body.allow_internal)
    pool = request.app.state.pool
    exists = await pool.fetchval("SELECT 1 FROM bridge_configs WHERE name=$1", body.name)
    if exists:
        raise HTTPException(status_code=409, detail="conflict: име заето")
    async with pool.acquire() as conn:
        async with conn.transaction():
            bid = await conn.fetchval(
                "INSERT INTO bridge_configs (name, direction, remote_host, remote_port,"
                " remote_username, remote_password, allow_internal, topic_map, rate_limit_per_min)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9) RETURNING id",
                body.name,
                body.direction,
                body.remote_host,
                body.remote_port,
                body.remote_username,
                body.remote_password,
                body.allow_internal,
                json.dumps(body.topic_map),
                body.rate_limit_per_min,
            )
            for rule in body.rules:
                await conn.execute(
                    "INSERT INTO bridge_rules (bridge_id, kind, topic_pattern,"
                    " payload_type, priority, reason) VALUES ($1,$2,$3,$4,$5,$6)",
                    bid,
                    rule.kind,
                    rule.topic_pattern,
                    rule.payload_type,
                    rule.priority,
                    rule.reason,
                )
    await audit(
        pool,
        user,
        "bridge.create",
        "bridge",
        body.name,
        {"remote": f"{body.remote_host}:{body.remote_port}", "rules": len(body.rules)},
    )
    return {"data": await _bridge_out(pool, str(bid))}


@router.delete("/{bridge_id}")
async def delete_bridge(
    bridge_id: str, request: Request, user: CurrentUser = Depends(require_admin)
):
    pool = request.app.state.pool
    name = await pool.fetchval(
        "DELETE FROM bridge_configs WHERE id=$1 RETURNING name", bridge_id
    )
    if not name:
        raise HTTPException(status_code=404, detail="not_found")
    await request.app.state.bridge.reload()
    await audit(pool, user, "bridge.delete", "bridge", name)
    return {"data": {"ok": True}}


@router.post("/{bridge_id}/enable")
async def enable_bridge(
    bridge_id: str,
    request: Request,
    body: dict | None = None,
    user: CurrentUser = Depends(require_admin),
):
    pool = request.app.state.pool
    bridge = await _bridge_out(pool, bridge_id)
    if bridge["direction"] in ("bidirectional", "inbound") and not (body or {}).get("confirm_risky"):
        raise HTTPException(
            status_code=409,
            detail="confirm_required: този вид мост изисква confirm_risky=true "
            "(внася външни данни — оцени rates/дедупликация)",
        )
    await pool.execute("UPDATE bridge_configs SET enabled=true WHERE id=$1", bridge_id)
    await request.app.state.bridge.reload()
    await audit(pool, user, "bridge.enable", "bridge", bridge["name"])
    return {"data": await _bridge_out(pool, bridge_id)}


@router.post("/{bridge_id}/disable")
async def disable_bridge(
    bridge_id: str, request: Request, user: CurrentUser = Depends(require_admin)
):
    pool = request.app.state.pool
    name = await pool.fetchval(
        "UPDATE bridge_configs SET enabled=false WHERE id=$1 RETURNING name", bridge_id
    )
    if not name:
        raise HTTPException(status_code=404, detail="not_found")
    await request.app.state.bridge.reload()
    await audit(pool, user, "bridge.disable", "bridge", name)
    return {"data": {"ok": True}}


class BridgeTestIn(BaseModel):
    topic: str
    payload: str


@router.post("/{bridge_id}/test")
async def test_bridge(
    bridge_id: str, body: BridgeTestIn, request: Request, user: CurrentUser = Depends(require_admin)
):
    """Dry-run: решението и причината, без реално препращане."""
    pool = request.app.state.pool
    info = await _bridge_out(pool, bridge_id)
    from ..bridge.rules import BridgePolicy, Rule

    policy = BridgePolicy(
        rules=[
            Rule(
                kind=r["kind"],
                topic_pattern=r["topic_pattern"],
                payload_type=r["payload_type"],
                priority=r["priority"],
                reason=r["reason"] or "",
            )
            for r in info["rules"]
        ],
        rate_limit_per_min=info["rate_limit_per_min"],
    )
    decision = policy.decide(body.topic, body.payload.encode(), "text", "local")
    return {"data": {"action": decision.action, "reason": decision.reason}}


@router.get("/{bridge_id}/events")
async def bridge_events(
    bridge_id: str,
    request: Request,
    decision: str | None = None,
    limit: int = 50,
    user: CurrentUser = Depends(require_viewer),
):
    limit = min(limit, 200)
    pool = request.app.state.pool
    if decision:
        rows = await pool.fetch(
            "SELECT ts, decision, topic, reason FROM bridge_events"
            " WHERE bridge_id=$1 AND decision=$2 ORDER BY ts DESC LIMIT $3",
            bridge_id,
            decision,
            limit,
        )
    else:
        rows = await pool.fetch(
            "SELECT ts, decision, topic, reason FROM bridge_events"
            " WHERE bridge_id=$1 ORDER BY ts DESC LIMIT $2",
            bridge_id,
            limit,
        )
    return {
        "data": [
            {
                "ts": r["ts"].isoformat(),
                "decision": r["decision"],
                "topic": r["topic"],
                "reason": r["reason"],
            }
            for r in rows
        ]
    }
