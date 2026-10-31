import hashlib
import os
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import asyncpg
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request

SESSION_COOKIE = "mg_session"
SESSION_TTL_SECONDS = 12 * 3600
ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}

# Начална парола по подразбиране (за първо влизане; gen-env.sh трябва да е
# синхронизиран с нея). Проверката дали още е в сила е динамична — по хеша.
DEFAULT_ADMIN_PASSWORD = "P@sswordG@te"

_ph = PasswordHasher()
_login_attempts: dict[str, deque[float]] = defaultdict(deque)
LOGIN_WINDOW_S = 60
# на IP; тестовете в контейнера споделят 127.0.0.1 с живите заявки, затова
# лимитът е конфигурируем (env MESHGATE_LOGIN_MAX); default 30/min остава
# разумна защита срещу brute-force отвън
LOGIN_MAX = int(os.environ.get("MESHGATE_LOGIN_MAX", "30"))


@dataclass
class CurrentUser:
    id: str
    username: str
    role: str


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def new_session_token() -> tuple[str, str]:
    """Връща (token, token_hash). По базата пазим само хеша."""
    token = secrets.token_urlsafe(32)
    return token, _token_hash(token)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    dq = _login_attempts[ip]
    while dq and now - dq[0] > LOGIN_WINDOW_S:
        dq.popleft()
    if len(dq) >= LOGIN_MAX:
        return True
    dq.append(now)
    return False


async def create_session(pool: asyncpg.Pool, user_id: str) -> str:
    token, token_hash = new_session_token()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at)"
            " VALUES ($1, $2, now() + make_interval(secs => $3))",
            token_hash,
            user_id,
            SESSION_TTL_SECONDS,
        )
    return token


async def resolve_session(pool: asyncpg.Pool, token: str | None) -> CurrentUser | None:
    if not token:
        return None
    row = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT u.id, u.username, u.role FROM sessions s"
            " JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = $1 AND s.expires_at > now() AND NOT u.disabled",
            _token_hash(token),
        )
    if not row:
        return None
    return CurrentUser(id=row["id"], username=row["username"], role=row["role"])


async def uses_default_password(pool: asyncpg.Pool) -> bool:
    """Истина, ако bootstrap администраторът все още ползва началната парола."""
    from .config import settings

    row = await pool.fetchrow(
        "SELECT password_hash FROM users WHERE username = $1",
        settings().meshgate_admin_user,
    )
    return bool(row) and verify_password(DEFAULT_ADMIN_PASSWORD, row["password_hash"])


async def current_user(request: Request) -> CurrentUser | None:
    pool = request.app.state.pool
    return await resolve_session(pool, request.cookies.get(SESSION_COOKIE))


def require(role: str):
    min_level = ROLE_ORDER[role]

    async def dep(request: Request) -> CurrentUser:
        user = await current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        if ROLE_ORDER[user.role] < min_level:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return dep


require_viewer = require("viewer")
require_operator = require("operator")
require_admin = require("admin")


async def audit(
    pool: asyncpg.Pool,
    user: CurrentUser | None,
    action: str,
    entity: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO audit_log (user_id, username, action, entity, entity_id, details)"
            " VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            user.id if user else None,
            user.username if user else None,
            action,
            entity,
            entity_id,
            __import__("json").dumps(details or {}),
        )
