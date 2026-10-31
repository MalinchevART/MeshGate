from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pydantic_core import PydanticCustomError

from ..security import CurrentUser, hash_password, require_admin
from ..security import audit

router = APIRouter(prefix="/v1/users", tags=["users"])


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(viewer|operator|admin)$")


@router.get("")
async def list_users(request: Request, user: CurrentUser = Depends(require_admin)):
    rows = await request.app.state.pool.fetch(
        "SELECT id, username, role, disabled, created_at FROM users ORDER BY created_at"
    )
    return {
        "data": [
            {
                "id": str(r["id"]),
                "username": r["username"],
                "role": r["role"],
                "disabled": r["disabled"],
            }
            for r in rows
        ]
    }


@router.post("", status_code=201)
async def create_user(body: UserIn, request: Request, user: CurrentUser = Depends(require_admin)):
    pool = request.app.state.pool
    exists = await pool.fetchval("SELECT 1 FROM users WHERE username=$1", body.username)
    if exists:
        raise HTTPException(status_code=409, detail="conflict: потребителят съществува")
    row = await pool.fetchrow(
        "INSERT INTO users (username, password_hash, role) VALUES ($1,$2,$3)"
        " RETURNING id, username, role",
        body.username,
        hash_password(body.password),
        body.role,
    )
    await audit(pool, user, "user.create", "user", body.username, {"role": body.role})
    return {"data": {"id": str(row["id"]), "username": row["username"], "role": row["role"]}}


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/{user_id}/password")
async def reset_password(
    user_id: str, body: ResetPasswordIn, request: Request,
    user: CurrentUser = Depends(require_admin),
):
    """Администратор сменя парола на друг потребител; сесиите му се прекъсват."""
    pool = request.app.state.pool
    changed = await pool.fetchrow(
        "UPDATE users SET password_hash = $1 WHERE id = $2 RETURNING username",
        hash_password(body.new_password),
        user_id,
    )
    if not changed:
        raise HTTPException(status_code=404, detail="not_found")
    await pool.execute("DELETE FROM sessions WHERE user_id = $1", user_id)
    await audit(pool, user, "user.password_reset", "user", changed["username"])
    return {"data": {"ok": True}}


@router.delete("/{user_id}")
async def delete_user(user_id: str, request: Request, user: CurrentUser = Depends(require_admin)):
    pool = request.app.state.pool
    target = await pool.fetchrow(
        "SELECT username, role FROM users WHERE id = $1", user_id
    )
    if not target:
        raise HTTPException(status_code=404, detail="not_found")
    if target["role"] == "admin":
        other_admins = await pool.fetchval(
            "SELECT count(*) FROM users WHERE role = 'admin' AND id != $1", user_id
        )
        if not other_admins:
            raise HTTPException(
                status_code=409,
                detail="conflict: последният администратор не може да бъде изтрит",
            )
    await pool.execute("DELETE FROM users WHERE id = $1", user_id)
    await audit(pool, user, "user.delete", "user", target["username"])
    return {"data": {"ok": True}}
