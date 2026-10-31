"""Т7 API: критични събития — списък/брояч + ack/silence/unsilence + прагове.

RBAC: четене = viewer+; ack/silence = operator+; прагове = admin.
Всяка мутация минава през audit. Контрактът на шел-брояча (docs/16 Т6):
counts.open е числото в чипа; events носят deep links за drill-down.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..critical import DEFAULTS, SETTINGS_KEY, thresholds
from ..security import CurrentUser, audit, require_admin, require_operator, require_viewer

router = APIRouter(prefix="/v1/critical-events", tags=["critical-events"])


def _payload(r) -> dict:
    """asyncpg връща jsonb като ТЕКСТ (урок от Фаза 5) — парсваме."""
    v = r["payload"]
    if isinstance(v, dict):
        return v
    try:
        out = json.loads(v) if v else {}
        return out if isinstance(out, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _row_to_event(r) -> dict:
    return {
        "id": str(r["id"]),
        "event_key": r["event_key"],
        "kind": r["kind"],
        "severity": r["severity"],
        "status": r["status"],
        "payload": _payload(r),
        "first_seen_at": r["first_seen_at"].isoformat(),
        "last_seen_at": r["last_seen_at"].isoformat(),
        "occurrences": r["occurrences"],
        "acked_by": r["acked_by"],
        "acked_at": r["acked_at"].isoformat() if r["acked_at"] else None,
        "silenced_until": r["silenced_until"].isoformat() if r["silenced_until"] else None,
        "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
    }


@router.get("")
async def list_critical_events(
    request: Request,
    status: str = "active",
    kind: str | None = None,
    hours: int = 168,
    limit: int = 100,
    offset: int = 0,
    user: CurrentUser = Depends(require_viewer),
):
    """status: active (open + silenced) | open | resolved | all."""
    pool = request.app.state.pool
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)
    hours = min(max(hours, 1), 720)

    if status not in ("active", "open", "resolved", "all"):
        raise HTTPException(422, "status трябва да е active|open|resolved|all")

    where = ["e.last_seen_at > now() - make_interval(hours => $1)"]
    args: list = [hours]
    if status == "active":
        where.append("e.status IN ('open','silenced')")
    elif status != "all":
        where.append("e.status = $2")
        args.append(status)
    if kind:
        where.append("e.kind = $%d" % (len(args) + 1))
        args.append(kind)

    rows = await pool.fetch(
        "SELECT e.* FROM critical_events e WHERE " + " AND ".join(where)
        + " ORDER BY e.last_seen_at DESC LIMIT $%d OFFSET $%d" % (len(args) + 1, len(args) + 2),
        *args, limit, offset)
    counts_rows = await pool.fetch(
        "SELECT status, count(*) AS n FROM critical_events"
        " WHERE last_seen_at > now() - make_interval(hours => $1) GROUP BY 1", hours)
    counts = {r["status"]: r["n"] for r in counts_rows}
    total = sum(counts.values())
    return {"data": {
        "hours": hours,
        "counts": {
            "open": counts.get("open", 0),
            "acked": counts.get("acked", 0),
            "silenced": counts.get("silenced", 0),
            "resolved": counts.get("resolved", 0),
            # числото в шел-чипа: всичко, което буди оператора
            "alarm": counts.get("open", 0),
            "total": total,
        },
        "events": [_row_to_event(r) for r in rows],
    }}


async def _load(pool, event_key: str) -> dict:
    # NUL байт от %00 в пътя — asyncpg го отхвърля с 500; той никога не е
    # валиден ключ → честна 404 (П2 сигурност F1)
    if "\x00" in event_key:
        raise HTTPException(404, "няма такова критично събитие")
    r = await pool.fetchrow(
        "SELECT * FROM critical_events WHERE event_key = $1", event_key)
    if r is None:
        raise HTTPException(404, "няма такова критично събитие")
    return dict(r)


@router.post("/{event_key}/ack")
async def ack_event(event_key: str, request: Request,
                    user: CurrentUser = Depends(require_operator)):
    pool = request.app.state.pool
    row = await _load(pool, event_key)
    if row["status"] == "resolved":
        raise HTTPException(409, "събитието вече е resolved")
    await pool.execute(
        "UPDATE critical_events SET status='acked', acked_by=$2, acked_at=now(),"
        " silenced_until=NULL, updated_at=now() WHERE event_key=$1",
        event_key, user.username)
    await audit(pool, user, "critical.ack", "critical_event", event_key, {})
    return {"data": {"event_key": event_key, "status": "acked"}}


class SilenceIn(BaseModel):
    hours: float = Field(default=4, ge=0.1, le=24 * 30)


@router.post("/{event_key}/silence")
async def silence_event(event_key: str, body: SilenceIn, request: Request,
                        user: CurrentUser = Depends(require_operator)):
    pool = request.app.state.pool
    row = await _load(pool, event_key)
    if row["status"] == "resolved":
        raise HTTPException(409, "събитието вече е resolved")
    until = datetime.now(timezone.utc) + timedelta(hours=body.hours)
    await pool.execute(
        "UPDATE critical_events SET status='silenced', silenced_until=$2,"
        " acked_by=$3, acked_at=now(), updated_at=now() WHERE event_key=$1",
        event_key, until, user.username)
    await audit(pool, user, "critical.silence", "critical_event", event_key,
                {"hours": body.hours})
    return {"data": {"event_key": event_key, "status": "silenced",
                     "silenced_until": until.isoformat()}}


@router.post("/{event_key}/unsilence")
async def unsilence_event(event_key: str, request: Request,
                          user: CurrentUser = Depends(require_operator)):
    pool = request.app.state.pool
    row = await _load(pool, event_key)
    if row["status"] not in ("silenced", "acked"):
        raise HTTPException(409, "само заглушено/потвърдено събитие може да се събуди")
    await pool.execute(
        "UPDATE critical_events SET status='open', silenced_until=NULL,"
        " acked_by=NULL, acked_at=NULL, updated_at=now() WHERE event_key=$1",
        event_key)
    await audit(pool, user, "critical.unsilence", "critical_event", event_key, {})
    return {"data": {"event_key": event_key, "status": "open"}}


# ---- прагове (settings ключ 'critical'; полета в System) -------------------

@router.get("/settings/thresholds")
async def get_thresholds(request: Request,
                         user: CurrentUser = Depends(require_viewer)):
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT value FROM settings WHERE key=$1", SETTINGS_KEY)
    cfg = None
    if row is not None:
        try:
            cfg = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
        except (json.JSONDecodeError, TypeError):
            cfg = None
    return {"data": {"defaults": DEFAULTS, "effective": thresholds(cfg),
                     "configured": cfg or {}}}


class ThresholdsIn(BaseModel):
    battery_pct: float | None = Field(default=None, ge=0, le=100)
    deadletter_24h: float | None = Field(default=None, ge=1, le=1000)
    silence_hours: float | None = Field(default=None, ge=0.5, le=24 * 30)


@router.put("/settings/thresholds")
async def put_thresholds(body: ThresholdsIn, request: Request,
                         user: CurrentUser = Depends(require_admin)):
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT value FROM settings WHERE key=$1", SETTINGS_KEY)
    cfg: dict = {}
    if row is not None:
        try:
            cfg = json.loads(row["value"]) if isinstance(row["value"], str) else dict(row["value"])
        except (json.JSONDecodeError, TypeError):
            cfg = {}
    for k, v in body.model_dump(exclude_none=True).items():
        cfg[k] = v
    await pool.execute(
        "INSERT INTO settings (key, value) VALUES ($1, $2::jsonb)"
        " ON CONFLICT (key) DO UPDATE SET value = $2::jsonb",
        SETTINGS_KEY, json.dumps(cfg))
    await audit(pool, user, "critical.thresholds", "settings", SETTINGS_KEY,
                {"set": body.model_dump(exclude_none=True)})
    return {"data": {"effective": thresholds(cfg)}}
