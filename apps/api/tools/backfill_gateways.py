"""Т37 backfill: гейтове×канали от записаните пакети (envelope gateway_id).

Някои стари записи нямат gateway_id в payload — те се пропускат (честно)."""
import asyncio
import json
import os
import sys

import asyncpg

sys.path.insert(0, "/srv")
from app.ingest.mesh_decode import decode_envelope_protobuf, envelope_info  # noqa: E402


def channel_of(topic: str) -> str:
    toks = topic.split("/")
    if len(toks) > 4 and toks[0] == "msh":
        return toks[4] if len(toks) > 4 else toks[0]
    return toks[0]


async def main() -> None:
    pool = await asyncpg.connect(
        host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        database=os.environ["PGDATABASE"])
    try:
        rows = await pool.fetch(
            "SELECT topic, payload_text, payload_raw, ts FROM packets"
            " WHERE ts > now() - interval '7 days' AND origin NOT LIKE 'routing:%'"
            " LIMIT 50000")
        agg: dict[tuple, int] = {}
        seen: dict[str, float] = {}
        for r in rows:
            gw = None
            try:
                info = envelope_info(r["payload_text"] or "")
                if info is None and r["payload_raw"]:
                    info = decode_envelope_protobuf(bytes(r["payload_raw"]))
                gw = (info or {}).get("gateway_id")
            except Exception:
                gw = None
            if not gw:
                continue
            key = (gw, channel_of(r["topic"]))
            agg[key] = agg.get(key, 0) + 1
            ts = r["ts"].timestamp()
            seen[gw] = max(seen.get(gw, 0), ts)
        n = 0
        for (gw, ch), cnt in agg.items():
            await pool.execute(
                "INSERT INTO gateway_channels (gateway_id, channel, packets)"
                " VALUES ($1,$2,$3)"
                " ON CONFLICT (gateway_id, channel) DO UPDATE SET"
                "  packets = GREATEST(gateway_channels.packets, EXCLUDED.packets)",
                gw, ch, cnt)
            n += 1
        for gw, ts in seen.items():
            await pool.execute(
                "INSERT INTO gateways (gateway_id, kind, last_heard)"
                " VALUES ($1, CASE WHEN $1 LIKE 'bridge:%' THEN 'bridge' ELSE 'mqtt' END,"
                " to_timestamp($2))"
                " ON CONFLICT (gateway_id) DO UPDATE SET"
                "  last_heard = GREATEST(gateways.last_heard, EXCLUDED.last_heard)",
                gw, ts)
        print(f"внесени {len(agg)} гейт×канал връзки, {len(seen)} гейта")
    finally:
        await pool.close()


asyncio.run(main())
