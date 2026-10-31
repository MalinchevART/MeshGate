"""Канали за известия (Фаза 5): Telegram / имейл / webhook + журнал + тест."""
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..notify.engine import config_public, config_valid
from ..security import CurrentUser, audit, require_admin, require_viewer

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class ChannelIn(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    kind: str = Field(pattern=r"^(telegram|email|webhook|whatsapp)$")
    topic_pattern: str = Field(min_length=1, max_length=256)
    config: dict = Field(default_factory=dict)
    # собствен формат на съобщението: {topic} {channel} {severity} {node}
    # {text} {battery} {snr} {rssi} {lat} {lng} {origin}; NULL → стандартният
    template: str | None = Field(default=None, max_length=500)
    # праг на важност: съобщения под нивото се пропускат (severity в payload)
    severity: str = Field(default="info", pattern=r"^(info|important|critical)$")
    min_interval_s: int = Field(ge=0, le=86400, default=30)
    enabled: bool = True
    # SSRF защита като при мостовете: вътрешни (loopback) webhook цели се
    # допускат само изрично — за тестове и вътрешни интеграции
    allow_internal: bool = False


def _validate_webhook_url(cfg: dict, allow_internal: bool) -> None:
    from .bridges import validate_remote_host

    url = str(cfg.get("url") or "")
    host = urlparse(url).hostname or ""
    if not host:
        raise HTTPException(status_code=422, detail="webhook без хост в url")
    validate_remote_host(host, allow_internal)


def _row(r) -> dict:
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "kind": r["kind"],
        "topic_pattern": r["topic_pattern"],
        "config": config_public(json.loads(r["config"]) if isinstance(r["config"], str) else r["config"]),
        "template": r["template"],
        "severity": r["severity"],
        "min_interval_s": r["min_interval_s"],
        "enabled": r["enabled"],
        "created_at": r["created_at"].isoformat(),
    }


@router.get("")
async def list_channels(request: Request, user: CurrentUser = Depends(require_viewer)):
    rows = await request.app.state.pool.fetch(
        "SELECT * FROM notification_channels ORDER BY created_at"
    )
    return {"data": [_row(r) for r in rows]}


@router.post("", status_code=201)
async def create_channel(body: ChannelIn, request: Request,
                         user: CurrentUser = Depends(require_admin)):
    ok, why = config_valid(body.kind, body.config)
    if not ok:
        raise HTTPException(status_code=422, detail=why)
    if body.kind == "webhook":
        _validate_webhook_url(body.config, allow_internal=body.allow_internal)
    pool = request.app.state.pool
    try:
        r = await pool.fetchrow(
            "INSERT INTO notification_channels (name, kind, topic_pattern, config,"
            " template, severity, min_interval_s, enabled)"
            " VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8)"
            " RETURNING *",
            body.name, body.kind, body.topic_pattern,
            json.dumps(body.config), body.template, body.severity,
            body.min_interval_s, body.enabled,
        )
    except Exception:
        raise HTTPException(status_code=409, detail="канал с такова име вече съществува")
    await request.app.state.notify.load()
    await audit(pool, user, "notify.channel.create", f"{body.kind} {body.name} → {body.topic_pattern}")
    return {"data": _row(r)}


@router.delete("/{channel_id}")
async def delete_channel(channel_id: str, request: Request,
                         user: CurrentUser = Depends(require_admin)):
    pool = request.app.state.pool
    n = await pool.execute(
        "DELETE FROM notification_channels WHERE id = $1::uuid", channel_id
    )
    if n == "DELETE 0":
        raise HTTPException(status_code=404, detail="няма такъв канал")
    await request.app.state.notify.load()
    await audit(pool, user, "notify.channel.delete", channel_id)
    return {"data": {"deleted": channel_id}}


@router.post("/{channel_id}/enable")
async def enable_channel(channel_id: str, request: Request,
                         user: CurrentUser = Depends(require_admin)):
    await request.app.state.pool.execute(
        "UPDATE notification_channels SET enabled = true WHERE id = $1::uuid", channel_id
    )
    await request.app.state.notify.load()
    return {"data": {"enabled": channel_id}}


@router.post("/{channel_id}/disable")
async def disable_channel(channel_id: str, request: Request,
                          user: CurrentUser = Depends(require_admin)):
    await request.app.state.pool.execute(
        "UPDATE notification_channels SET enabled = false WHERE id = $1::uuid", channel_id
    )
    await request.app.state.notify.load()
    return {"data": {"disabled": channel_id}}


@router.post("/{channel_id}/test")
async def test_channel(channel_id: str, request: Request,
                       user: CurrentUser = Depends(require_admin)):
    notify = request.app.state.notify
    row = await request.app.state.pool.fetchrow(
        "SELECT * FROM notification_channels WHERE id = $1::uuid", channel_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="няма такъв канал")
    ch = dict(row)
    ch["config"] = json.loads(ch["config"]) if isinstance(ch["config"], str) else ch["config"]
    try:
        await notify.send_test(ch)
    except Exception as exc:
        await notify._log(ch, "meshgate/test", "Тестово известие от MeshGate ✓",
                          "failed", str(exc)[:300])
        raise HTTPException(status_code=502, detail=f"изпращането се провали: {str(exc)[:200]}")
    await notify._log(ch, "meshgate/test", "Тестово известие от MeshGate ✓", "sent", None)
    return {"data": {"sent": True}}


@router.get("/digest")
async def digest_preview(request: Request,
                         user: CurrentUser = Depends(require_viewer)):
    """Преглед на сутрешния бриф (какъв би отишло в канала с digest_hour)."""
    from ..notify.engine import build_digest

    return {"data": {"text": await build_digest(request.app.state.pool)}}


@router.get("/log")
async def notification_log(request: Request, limit: int = 50,
                           user: CurrentUser = Depends(require_viewer)):
    limit = min(max(limit, 1), 500)
    rows = await request.app.state.pool.fetch(
        "SELECT l.id, l.topic, l.message, l.status, l.error, l.ts, c.name AS channel"
        " FROM notification_log l LEFT JOIN notification_channels c ON c.id = l.channel_id"
        " ORDER BY l.id DESC LIMIT $1",
        limit,
    )
    return {
        "data": [
            {
                "id": r["id"], "channel": r["channel"], "topic": r["topic"],
                "message": r["message"], "status": r["status"],
                "error": r["error"], "ts": r["ts"].isoformat(),
            }
            for r in rows
        ]
    }
