import json

from fastapi import APIRouter, Depends, Request

from ..security import CurrentUser, require_admin

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("")
async def list_audit(
    request: Request,
    action: str | None = None,
    username: str | None = None,
    limit: int = 50,
    user: CurrentUser = Depends(require_admin),
):
    limit = min(limit, 200)
    where = ["TRUE"]
    args: list = []
    if action:
        args.append(action)
        where.append(f"action = ${len(args)}")
    if username:
        args.append(username)
        where.append(f"username = ${len(args)}")
    args.append(limit)
    rows = await request.app.state.pool.fetch(
        f"SELECT ts, username, action, entity, entity_id, details FROM audit_log"
        f" WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ${len(args)}",
        *args,
    )
    return {
        "data": [
            {
                "ts": r["ts"].isoformat(),
                "username": r["username"],
                "action": r["action"],
                "entity": r["entity"],
                "entity_id": r["entity_id"],
                "details": json.loads(r["details"]),
            }
            for r in rows
        ]
    }
