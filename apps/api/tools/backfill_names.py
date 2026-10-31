"""Т36 backfill: внася имената на възлите от вече записаните NODEINFO /
MAP_REPORT пакети (payload_raw/payload_text). Еднократен скрипт."""
import asyncio
import base64
import json
import os
import sys

import asyncpg

sys.path.insert(0, "/srv")
from app.ingest.mesh_decode import _parse_user, decode_envelope_protobuf, envelope_info  # noqa: E402


async def main() -> None:
    pool = await asyncpg.connect(
        host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        database=os.environ["PGDATABASE"])
    try:
        rows = await pool.fetch(
            "SELECT topic, payload_text, payload_raw FROM packets"
            " WHERE packet_type IN ('meshtastic-nodeinfo', 'meshtastic-map')"
            "   AND ts > now() - interval '7 days' LIMIT 20000")
        learned = {}
        for r in rows:
            try:
                info = envelope_info(r["payload_text"] or "")
                if info is None and r["payload_raw"]:
                    info = decode_envelope_protobuf(bytes(r["payload_raw"]))
                if not info:
                    continue
                u = info.get("user")
                node = info.get("node_id") or ""
                if not u or not node:
                    continue
                cur = learned.get(node.lower())
                if cur is None:
                    learned[node.lower()] = {
                        "long": u.get("long_name"), "short": u.get("short_name"),
                        "hw": u.get("hw_model"), "role": u.get("role"),
                        "fp": u.get("pubkey_fp")}
                else:  # пази най-богатото
                    for k, kk in (("long_name", "long"), ("short_name", "short"),
                                  ("hw_model", "hw"), ("role", "role"), ("pubkey_fp", "fp")):
                        if u.get(k) and not cur[kk]:
                            cur[kk] = u.get(k)
            except Exception:
                continue
        n = 0
        for node, v in learned.items():
            await pool.execute(
                "INSERT INTO node_registry (node_id, long_name, short_name, hw_model, role, pubkey_fp)"
                " VALUES ($1,$2,$3,$4,$5,$6)"
                " ON CONFLICT (node_id) DO UPDATE SET"
                "  long_name = COALESCE(node_registry.long_name, EXCLUDED.long_name),"
                "  short_name = COALESCE(node_registry.short_name, EXCLUDED.short_name),"
                "  hw_model = COALESCE(node_registry.hw_model, EXCLUDED.hw_model),"
                "  role = COALESCE(node_registry.role, EXCLUDED.role),"
                "  pubkey_fp = COALESCE(node_registry.pubkey_fp, EXCLUDED.pubkey_fp),"
                "  last_heard = now()",
                node, v["long"], v["short"], v["hw"], v["role"], v["fp"])
            n += 1
        total = await pool.fetchval("SELECT count(*) FROM node_registry")
        print(f"внесени {n} възела; регистърът вече има {total} имена")
    finally:
        await pool.close()


asyncio.run(main())
