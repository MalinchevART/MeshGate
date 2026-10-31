import json
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..security import CurrentUser, audit, require_admin, require_viewer

router = APIRouter(prefix="/v1/profiles", tags=["profiles"])


class ProfileSpec(BaseModel):
    """Какво контролира един профил в MVP обхвата (виж docs/04-mvp-scope.md)."""

    retention_packets_raw: int = Field(ge=1, le=3650, default=14)
    retention_events: int = Field(ge=1, le=3650, default=365)
    bridge_outbound_enabled: bool = False
    packet_explorer_live: bool = True


def spec_to_settings(spec: ProfileSpec) -> dict[str, Any]:
    return {
        "retention": {
            "packets_raw_days": spec.retention_packets_raw,
            "events_days": spec.retention_events,
        },
        "bridge_outbound_enabled": spec.bridge_outbound_enabled,
        "packet_explorer_live": spec.packet_explorer_live,
    }


def diff_settings(before: dict, after: dict) -> dict:
    out = {}
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            out[key] = {"before": before.get(key), "after": after.get(key)}
    return out


FACTORY_PROFILES: dict[str, dict] = {
    "home-gateway": {
        "description": "Локален брокер за HA/Z2M; без изходящо препращане.",
        "spec": {"retention_packets_raw": 14, "retention_events": 365,
                 "bridge_outbound_enabled": False, "packet_explorer_live": True},
    },
    "mesh-monitor": {
        "description": "Колектори и архив на mesh събития; Packet Explorer.",
        "spec": {"retention_packets_raw": 30, "retention_events": 365,
                 "bridge_outbound_enabled": False, "packet_explorer_live": True},
    },
    "isolated-lab": {
        "description": "Изолирана тестова среда; мостове изключени.",
        "spec": {"retention_packets_raw": 7, "retention_events": 90,
                 "bridge_outbound_enabled": False, "packet_explorer_live": True},
    },
    "controlled-public-bridge": {
        "description": "Изрично разрешени изходящи теми с лимити.",
        "spec": {"retention_packets_raw": 14, "retention_events": 365,
                 "bridge_outbound_enabled": True, "packet_explorer_live": True},
    },
    "developer-debug": {
        "description": "Кратка ретенция, всичко видно, без мостове.",
        "spec": {"retention_packets_raw": 3, "retention_events": 30,
                 "bridge_outbound_enabled": False, "packet_explorer_live": True},
    },
}


@router.get("")
async def list_profiles(request: Request, user: CurrentUser = Depends(require_viewer)):
    rows = await request.app.state.pool.fetch(
        "SELECT p.id, p.name, p.description, max(v.version) AS current_version"
        " FROM profiles p JOIN profile_versions v ON v.profile_id = p.id"
        " GROUP BY p.id, p.name, p.description ORDER BY p.name"
    )
    return {
        "data": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "description": r["description"],
                "current_version": r["current_version"],
            }
            for r in rows
        ]
    }


@router.post("/validate")
async def validate_spec(body: dict, request: Request, user: CurrentUser = Depends(require_admin)):
    try:
        ProfileSpec(**body)
    except Exception as exc:
        return {"data": {"valid": False, "errors": str(exc)}}
    return {"data": {"valid": True, "errors": None}}


async def _apply_version(pool, request, user: CurrentUser, profile_name: str, version: int):
    row = await pool.fetchrow(
        "SELECT v.id, v.spec, v.version, p.name FROM profile_versions v"
        " JOIN profiles p ON p.id = v.profile_id WHERE p.name = $1 AND v.version = $2",
        profile_name,
        version,
    )
    if not row:
        raise HTTPException(status_code=404, detail="not_found: версията не съществува")
    spec = ProfileSpec(**json.loads(row["spec"]))
    new_settings = spec_to_settings(spec)
    before: dict[str, Any] = {}
    for key in new_settings:
        raw = await pool.fetchval(
            "SELECT value FROM settings WHERE key = $1", key
        )
        before[key] = json.loads(raw) if raw is not None else None
    diff = diff_settings(before, new_settings)
    return new_settings, before, diff


@router.post("/{profile_name}/apply")
async def apply_profile(
    profile_name: str,
    request: Request,
    body: dict,
    user: CurrentUser = Depends(require_admin),
):
    version = int(body.get("version", 0))
    confirm = bool(body.get("confirm_risky", False))
    pool = request.app.state.pool
    new_settings, before, diff = await _apply_version(pool, request, user, profile_name, version)

    risky = diff.get("bridge_outbound_enabled", {}).get("after") is True
    if risky and not confirm:
        # НИЩО не се прилага преди изричното потвърждение
        return {
            "data": {
                "applied": False,
                "requires_confirmation": True,
                "risky": True,
                "diff": diff,
            }
        }

    async with pool.acquire() as conn:
        async with conn.transaction():
            for key, value in new_settings.items():
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ($1, $2::jsonb)"
                    " ON CONFLICT (key) DO UPDATE SET value = $2::jsonb, updated_at = now()",
                    key,
                    json.dumps(value),
                )
            await conn.execute(
                "INSERT INTO configuration_changes (user_id, scope, before, after, diff)"
                " VALUES ($1, 'profile', $2::jsonb, $3::jsonb, $4::jsonb)",
                user.id,
                json.dumps(before),
                json.dumps({"profile": profile_name, "version": version}),
                json.dumps(diff),
            )
    await audit(
        pool, user, "profile.apply", "profile", profile_name,
        {"version": version, "diff": diff},
    )
    return {
        "data": {
            "applied": f"{profile_name} v{version}",
            "requires_confirmation": False,
            "risky": risky,
            "diff": diff,
        }
    }


@router.get("/{profile_name}/versions")
async def profile_versions(
    profile_name: str, request: Request, user: CurrentUser = Depends(require_viewer)
):
    rows = await request.app.state.pool.fetch(
        "SELECT v.version, v.spec, v.created_at FROM profile_versions v"
        " JOIN profiles p ON p.id = v.profile_id WHERE p.name = $1 ORDER BY v.version",
        profile_name,
    )
    return {
        "data": [
            {"version": r["version"], "spec": json.loads(r["spec"]),
             "created_at": r["created_at"].isoformat()}
            for r in rows
        ]
    }
