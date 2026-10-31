"""Обща подготовка за интеграционните тестове.

Тестовете НЕ ползват паролата на собственика (той я сменя през UI/съветника) —
имат собствен потребител mg-itest, който се създава/освежава преди всеки модул.
Роля admin, защото тестовете проверяват и административни операции."""

import os

import asyncpg

from app.security import hash_password

ITEST = {"username": "mg-itest", "password": "itest-pass-1234"}


async def ensure_itest_admin() -> None:
    conn = await asyncpg.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        database=os.environ["PGDATABASE"],
    )
    try:
        await conn.execute(
            "INSERT INTO users (username, password_hash, role, disabled)"
            " VALUES ($1, $2, 'admin', false)"
            " ON CONFLICT (username) DO UPDATE SET"
            " password_hash = $2, role = 'admin', disabled = false",
            ITEST["username"],
            hash_password(ITEST["password"]),
        )
    finally:
        await conn.close()
