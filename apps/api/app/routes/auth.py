from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import security
from ..security import audit, login_rate_limited, require_viewer

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    if login_rate_limited(ip):
        raise HTTPException(status_code=429, detail="rate_limited")
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "SELECT id, password_hash, role, disabled FROM users WHERE username = $1",
        body.username,
    )
    if not row or row["disabled"] or not security.verify_password(
        body.password, row["password_hash"]
    ):
        await audit(pool, None, "auth.login_failed", "user", body.username, {"ip": ip})
        raise HTTPException(status_code=401, detail="unauthorized")
    token = await security.create_session(pool, row["id"])
    response.set_cookie(
        security.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=security.SESSION_TTL_SECONDS,
    )
    await audit(pool, None, "auth.login", "user", body.username, {"ip": ip})
    return {
        "data": {
            "username": body.username,
            "role": row["role"],
            "default_password": await security.uses_default_password(pool),
        }
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(security.SESSION_COOKIE)
    if token:
        await request.app.state.pool.execute(
            "DELETE FROM sessions WHERE token_hash = $1", security._token_hash(token)
        )
    response.delete_cookie(security.SESSION_COOKIE)
    return {"data": {"ok": True}}


@router.get("/me")
async def me(request: Request):
    user = await security.current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return {
        "data": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "default_password": await security.uses_default_password(request.app.state.pool),
        }
    }


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, request: Request):
    """Всеки вписан потребител сменя СОБСТВЕНАТА си парола; останалите му
    сесии се прекъсват, текущата остава."""
    pool = request.app.state.pool
    user = await security.current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    row = await pool.fetchrow(
        "SELECT id, password_hash FROM users WHERE id = $1", user.id
    )
    if not row or not security.verify_password(body.old_password, row["password_hash"]):
        raise HTTPException(status_code=403, detail="forbidden: грешна текуща парола")
    await pool.execute(
        "UPDATE users SET password_hash = $1 WHERE id = $2",
        security.hash_password(body.new_password),
        user.id,
    )
    current_hash = security._token_hash(request.cookies.get(security.SESSION_COOKIE, ""))
    await pool.execute(
        "DELETE FROM sessions WHERE user_id = $1 AND token_hash != $2",
        user.id,
        current_hash,
    )
    await audit(pool, user, "user.password_change", "user", user.username)
    return {"data": {"ok": True}}
