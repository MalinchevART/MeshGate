"""Т37 API: гейтове×канали — кръстосаната референция (кой гейт кой канал
излъчва; кой канал през кои гейтове; имена от регистъра, път през мостове)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from ..security import CurrentUser, require_viewer


def _jsonb(v):
    """asyncpg връща jsonb като ТЕКСТ (урокът от Фаза 5)."""
    if isinstance(v, (list, dict)) or v is None:
        return v or []
    try:
        out = json.loads(v)
        return out if isinstance(out, list) else []
    except (json.JSONDecodeError, TypeError):
        return []

router = APIRouter(prefix="/v1/gateways", tags=["gateways"])


@router.get("")
async def gateways(request: Request, hours: int = 24,
                   user: CurrentUser = Depends(require_viewer)):
    """Списък: гейт → каналите, които излъчва (с бройки) + име от регистъра
    + от кого е чут (път: директен/мост). hours клампва 1..720."""
    pool = request.app.state.pool
    hours = min(max(hours, 1), 720)
    rows = await pool.fetch(
        "SELECT g.gateway_id, g.kind, g.first_seen, g.last_heard,"
        " r.short_name, r.long_name,"
        " (SELECT jsonb_agg(jsonb_build_object('channel', c.channel,"
        "   'packets', c.packets, 'last_ts', c.last_ts) ORDER BY c.packets DESC)"
        "  FROM gateway_channels c WHERE c.gateway_id = g.gateway_id"
        "    AND c.last_ts > now() - make_interval(hours => $1)) AS channels,"
        " (SELECT sum(c.packets) FROM gateway_channels c"
        "  WHERE c.gateway_id = g.gateway_id"
        "    AND c.last_ts > now() - make_interval(hours => $1)) AS packets"
        " FROM gateways g"
        " LEFT JOIN node_registry r ON r.node_id = lower(g.gateway_id)"
        " WHERE g.last_heard > now() - make_interval(hours => $1)"
        " ORDER BY packets DESC NULLS LAST",
        hours)
    return {"data": {
        "hours": hours,
        "gateways": [
            {
                "gateway_id": r["gateway_id"],
                "kind": r["kind"],
                "name": r["short_name"] or r["long_name"],
                "long_name": r["long_name"],
                "packets": int(r["packets"] or 0),
                "channels": _jsonb(r["channels"]),
                "first_seen": r["first_seen"].isoformat(),
                "last_heard": r["last_heard"].isoformat(),
            }
            for r in rows
        ],
    }}


@router.get("/channels")
async def channels_crossref(request: Request, hours: int = 24,
                            user: CurrentUser = Depends(require_viewer)):
    """Обратната посока: канал → през кои гейтове минава (и бройки)."""
    pool = request.app.state.pool
    hours = min(max(hours, 1), 720)
    rows = await pool.fetch(
        "SELECT c.channel, sum(c.packets) AS packets,"
        " jsonb_agg(jsonb_build_object('gateway', c.gateway_id,"
        "   'packets', c.packets) ORDER BY c.packets DESC) AS gateways"
        " FROM gateway_channels c"
        " WHERE c.last_ts > now() - make_interval(hours => $1)"
        " GROUP BY c.channel ORDER BY packets DESC",
        hours)
    return {"data": {
        "hours": hours,
        "channels": [
            {
                "channel": r["channel"],
                "packets": int(r["packets"] or 0),
                "gateways": _jsonb(r["gateways"]),
            }
            for r in rows
        ],
    }}
