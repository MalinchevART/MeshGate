import asyncio
import pathlib

import asyncpg

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


async def connect() -> asyncpg.Pool:
    from .config import settings

    s = settings()
    return await asyncpg.create_pool(
        host=s.pg_host,
        port=s.pg_port,
        user=s.pg_user,
        password=s.pg_password,
        database=s.pg_database,
        min_size=2,
        max_size=10,
    )


async def migrate(pool: asyncpg.Pool) -> list[str]:
    """Прилага SQL миграциите последователно, под cluster-wide заключване."""
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        lock = await conn.fetchval("SELECT pg_try_advisory_lock(918273645)")
        if not lock:
            # друг процес мигрира в момента — изчакваме да свърши
            while await conn.fetchval(
                "SELECT count(*) FROM schema_migrations WHERE name = ANY($1::text[])",
                [p.name for p in sorted(MIGRATIONS_DIR.glob("*.sql"))],
            ) < len(list(MIGRATIONS_DIR.glob("*.sql"))):
                await asyncio.sleep(1)
            return []
        try:
            done = {
                r["name"]
                for r in await conn.fetch("SELECT name FROM schema_migrations")
            }
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                sql = path.read_text(encoding="utf-8")
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (name) VALUES ($1)", path.name
                    )
                applied.append(path.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(918273645)")
    return applied
