import json

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Request

from ..security import CurrentUser, audit, require_admin, require_operator, require_viewer

router = APIRouter(prefix="/v1/devices", tags=["devices"])


@router.get("/map")
async def device_map(request: Request, hours: int = 24,
                     user: CurrentUser = Depends(require_viewer)):
    """Карта на възлите: последна позиция на всеки Meshtastic възел през
    последните N часа + батерия/канал/свежест за надписа. Позициите идват от
    декодирани meshtastic-position пакети (JSON или protobuf)."""
    from ..ingest.mesh_decode import (
        decode_envelope_protobuf, envelope_info, topic_parts)

    hours = min(max(hours, 1), 168)
    pool = request.app.state.pool

    async def _decode_rows(rows):
        """rows → {node: {lat,lng,ts,channel}} като се пази само новото."""
        out: dict[str, dict] = {}
        for r in rows:  # подредени DESC — първото срещане е най-новото
            info = envelope_info(r["payload_text"] or "")
            if info is None and r["payload_raw"]:
                info = decode_envelope_protobuf(
                bytes(r["payload_raw"]),
                getattr(getattr(request.app.state, "ingest", None), "psk_map", None))
            if not info or info["lat"] is None or info["lng"] is None:
                continue
            parts = topic_parts(r["topic"])
            node = info["node_id"] or parts["node"]
            if not node or node in out:
                continue
            out[node] = {"lat": info["lat"], "lng": info["lng"],
                         "ts": r["ts"].isoformat(),
                         "channel": parts["channel"] or info.get("channel_id")}
        return out

    pos_rows = await pool.fetch(
        "SELECT topic, payload_text, payload_raw, ts FROM packets"
        " WHERE topic LIKE 'msh/%' AND packet_type = 'meshtastic-position'"
        " AND ts > now() - make_interval(hours => $1)"
        " ORDER BY ts DESC LIMIT 2000",
        hours,
    )
    positions = await _decode_rows(pos_rows)
    if not positions:
        return {"data": {"hours": hours, "nodes": []}}

    # батария/канал/свежест/трафик за възлите с позиция
    nodes = set(positions)
    extra_rows = await pool.fetch(
        "SELECT topic, payload_text, payload_raw, ts FROM packets"
        " WHERE topic LIKE 'msh/%' AND packet_type = 'meshtastic-telemetry'"
        " AND ts > now() - make_interval(hours => $1)"
        " ORDER BY ts DESC LIMIT 3000",
        hours,
    )
    batteries: dict[str, tuple] = {}
    for r in extra_rows:
        info = envelope_info(r["payload_text"] or "")
        if info is None and r["payload_raw"]:
            info = decode_envelope_protobuf(
                bytes(r["payload_raw"]),
                getattr(getattr(request.app.state, "ingest", None), "psk_map", None))
        if not info or info["battery"] is None:
            continue
        node = info["node_id"] or topic_parts(r["topic"])["node"]
        if node in nodes and (node not in batteries
                              or r["ts"] > batteries[node][1]):
            batteries[node] = (info["battery"], r["ts"])

    traffic = {
        r["node"]: {"n": r["n"], "last": r["last"]}
        for r in await pool.fetch(
            "SELECT (regexp_match(topic, '(![0-9a-fA-F]+)$'))[1] AS node,"
            " count(*) AS n, max(ts) AS last FROM packets"
            " WHERE topic LIKE 'msh/%' AND ts > now() - make_interval(hours => $1)"
            " GROUP BY 1",
            hours,
        )
        if r["node"]
    }

    names = {
        r["node_id"]: r
        for r in await pool.fetch(
            "SELECT node_id, long_name, short_name FROM node_registry")
    }
    dev_rows = await pool.fetch(
        "SELECT id, external_id, routing_priority FROM devices"
        " WHERE protocol = 'meshtastic'")
    devs = {r["external_id"].lower(): r for r in dev_rows}
    out = []
    for node, p in positions.items():
        bat = batteries.get(node)
        tr = traffic.get(node)
        nm = names.get(node.lower())
        dv = devs.get(node.lower())
        out.append({
            "node": node, "lat": p["lat"], "lng": p["lng"], "position_ts": p["ts"],
            "channel": p["channel"],
            "battery": bat[0] if bat else None,
            "packets": tr["n"] if tr else 0,
            "last_seen": tr["last"].isoformat() if tr else p["ts"],
            "short_name": nm["short_name"] if nm else None,
            "long_name": nm["long_name"] if nm else None,
            "id": str(dv["id"]) if dv else None,
            "routing_priority": dv["routing_priority"] if dv else "normal",
        })
    out.sort(key=lambda x: -x["packets"])
    return {"data": {"hours": hours, "nodes": out}}


# Т10: SNR легендата на картата чете праговете от settings (ключ 'map'),
# не ги захардкодва — моделът е като critical thresholds
SNR_DEFAULTS = {"good_db": -8.0, "fair_db": -15.0}


@router.get("/map/thresholds")
async def map_snr_thresholds(request: Request,
                             user: CurrentUser = Depends(require_viewer)):
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT value FROM settings WHERE key='map'")
    cfg: dict = {}
    if row is not None:
        try:
            cfg = json.loads(row["value"]) if isinstance(row["value"], str) else dict(row["value"])
        except (json.JSONDecodeError, TypeError):
            cfg = {}
    effective = {**SNR_DEFAULTS}
    for k in SNR_DEFAULTS:
        if isinstance(cfg.get(k), (int, float)):
            effective[k] = float(cfg[k])
    return {"data": {"defaults": SNR_DEFAULTS, "effective": effective}}


@router.get("/pulse")
async def device_pulse(request: Request, hours: int = 24, daily: bool = False,
                       user: CurrentUser = Depends(require_viewer)):
    """Пулс на възлите (docs/15 Вълна 1): кофи по час (или по ДЕН при
    daily=1 — 7д изглед с hours=168) × клас чуване — чисто / само
    криптирано / служебни / мълчание + среден SNR на кофа (от events).
    Възлите lower-case, подредени и капнати на 500 в SQL."""
    hours = min(max(hours, 1), 168)
    grain = "day" if daily else "hour"
    window_units = (hours + 23) // 24 if daily else hours
    # дневен режим: прозорецът е N ДНИ назад (make_interval(days)), часови — N часа
    back = (f"make_interval(days => $1 - 1)" if daily
            else f"make_interval(hours => $1 - 1)")
    pool = request.app.state.pool
    # двустепенна агрегация: стъпка 1 групира суровите редове по (тема, кофа)
    # — само индексирани колони, нула regex; стъпка 2 вади възела с regex от
    # ~стотинте групи, а не от всеки от стотиците хиляди редове (7д ≈ 110K
    # реда, но само ~630 теми; регексът върху всеки ред гърбеше ~2.5s CPU)
    rows = await pool.fetch(
        f"WITH per AS ("
        f" SELECT topic,"
        f" date_trunc('{grain}', ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS bucket,"
        f" count(*) FILTER (WHERE packet_type IN"
        f"  ('meshtastic-text','meshtastic-nodeinfo','meshtastic-map')) AS plain,"
        f" count(*) FILTER (WHERE packet_type = 'meshtastic-encrypted') AS encrypted,"
        f" count(*) FILTER (WHERE packet_type NOT IN"
        f"  ('meshtastic-text','meshtastic-nodeinfo','meshtastic-map',"
        f"   'meshtastic-encrypted')) AS other"
        f" FROM packets"
        f" WHERE topic LIKE 'msh/%'"
        f"   AND ts >= date_trunc('{grain}', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        f"           - {back}"
        f" GROUP BY 1, 2"
        f"), per2 AS ("
        f" SELECT lower((regexp_match(topic, '(![0-9a-fA-F]+)$'))[1]) AS node,"
        f" bucket,"
        f" sum(plain)::int AS plain, sum(encrypted)::int AS encrypted,"
        f" sum(other)::int AS other"
        f" FROM per GROUP BY 1, 2"
        f"), top AS ("
        f" SELECT node FROM per2 GROUP BY node ORDER BY max(bucket) DESC LIMIT 500"
        f")"
        f" SELECT per2.node, per2.bucket, per2.plain, per2.encrypted, per2.other"
        f" FROM per2 JOIN top USING (node) ORDER BY per2.node, per2.bucket",
        window_units,
    )
    # среден SNR на кофа — от events.payload->decoded (пакетната таблица
    # няма snr колона; това е евтината странична агрегация)
    snr_rows = await pool.fetch(
        f"SELECT lower(d.external_id) AS node,"
        f" date_trunc('{grain}', e.ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS bucket,"
        f" round(avg((e.payload->'decoded'->>'snr')::numeric), 1) AS snr"
        f" FROM events e JOIN devices d ON d.id = e.device_id"
        f" WHERE e.ts >= date_trunc('{grain}', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        f"   - {back}"
        f"   AND e.payload->'decoded'->>'snr' IS NOT NULL"
        f" GROUP BY 1, 2",
        window_units,
    )
    snr_by: dict[tuple, float] = {}
    for r in snr_rows:
        snr_by[(r["node"], r["bucket"].isoformat())] = float(r["snr"])

    out: list[dict] = []
    cur: dict | None = None
    for r in rows:  # подредени по node, bucket
        if cur is None or cur["node"] != r["node"]:
            cur = {"node": r["node"], "buckets": [], "last": None}
            out.append(cur)
        t_iso = r["bucket"].isoformat()
        cur["buckets"].append({
            "t": t_iso,
            "plain": r["plain"], "encrypted": r["encrypted"],
            "other": r["other"],
            "snr": snr_by.get((r["node"], t_iso)),
        })
        cur["last"] = t_iso
    return {"data": {"hours": hours, "daily": daily, "nodes": out}}


async def _topology_edges(pool, hours: int) -> list:
    """Ребра „кой кого чу" от NeighborInfo. П3 Т28: на живата BG мрежа
    NeighborInfo върви В КРИПТИРАНИ пакети — packets.packet_type
    'meshtastic-neighbor' не се среща (0 реда); данните живеят в
    events.payload->decoded->neighbors (декодерът ги извлича и от
    криптиран envelope). Споделен от /v1/devices/topology, /v1/dashboard
    (Т8) и водопада (Т28) — картата и KPI „RF връзки" не могат да се
    разминат."""
    rows = await pool.fetch(
        "SELECT lower(d.external_id) AS frm, lower(nb->>'node') AS nb_node,"
        " max(e.ts) AS last, count(*) AS packets,"
        " avg(nullif(nb->>'snr','')::numeric) AS snr_avg,"
        " max(nullif(nb->>'snr','')::numeric) AS snr_max"
        " FROM events e JOIN devices d ON d.id = e.device_id"
        " CROSS JOIN LATERAL jsonb_array_elements(e.payload->'decoded'->'neighbors') AS nb"
        " WHERE e.ts > now() - make_interval(hours => $1)"
        "   AND jsonb_typeof(e.payload->'decoded'->'neighbors') = 'array'"
        "   AND coalesce(nb->>'node','') LIKE '!%'"
        " GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 400",
        hours,
    )
    return [
        {
            "from": r["frm"], "to": r["nb_node"],
            "snr_avg": round(float(r["snr_avg"]), 1) if r["snr_avg"] is not None else None,
            "snr_max": round(float(r["snr_max"]), 1) if r["snr_max"] is not None else None,
            "packets": int(r["packets"]),
            "last": r["last"].isoformat(),
        }
        for r in rows
    ]


@router.get("/topology")
async def device_topology(request: Request, hours: int = 24,
                          user: CurrentUser = Depends(require_viewer)):
    """Ребра „кой кого чу": NeighborInfo пакетите от последните N часа,
    агрегирани по двойка възли (брой, средно/макс SNR, последно виждане).
    Източник на линиите върху Картата."""
    hours = min(max(hours, 1), 168)
    pool = request.app.state.pool
    out = await _topology_edges(pool, hours)
    return {"data": {
        "hours": hours,
        "edges": out,
        "nodes": len({x["from"] for x in out} | {x["to"] for x in out}),
    }}


@router.get("")
async def list_devices(request: Request,
                       filter: str | None = None,
                       user: CurrentUser = Depends(require_viewer)):
    where = "TRUE"
    if filter == "muted":
        where = "d.muted"
    elif filter == "blocked":
        where = "d.blocked"
    elif filter == "active":
        where = "NOT d.muted AND NOT d.blocked"
    rows = await request.app.state.pool.fetch(
        f"SELECT d.id, d.protocol, d.external_id, d.name, d.status,"
        " d.muted, d.blocked, d.first_seen_at, d.last_seen_at, d.routing_priority,"
        " d.hold_back,"
        " (SELECT count(*) FROM events e WHERE e.device_id = d.id) AS events_count,"
        " r.long_name, r.short_name"
        f" FROM devices d"
        f" LEFT JOIN node_registry r ON r.node_id = lower(d.external_id)"
        f" WHERE {where} ORDER BY d.last_seen_at DESC LIMIT 500"
    )
    return {
        "data": [
            {
                "id": str(r["id"]),
                "protocol": r["protocol"],
                "external_id": r["external_id"],
                "name": r["name"],
                "status": "muted" if r["muted"] else ("blocked" if r["blocked"] else r["status"]),
                "muted": r["muted"],
                "blocked": r["blocked"],
                "first_seen_at": r["first_seen_at"].isoformat(),
                "last_seen_at": r["last_seen_at"].isoformat(),
                "events_count": r["events_count"],
                "long_name": r["long_name"],
                "short_name": r["short_name"],
                "routing_priority": r["routing_priority"],
                "hold_back": r["hold_back"],
            }
            for r in rows
        ]
    }


# ---------- Т28: Водопад (връзки×време) + Т29: Ефир-часовник ----------------

def air_clock_verdict(cells: list, days_covered: float, now=None) -> dict:
    """Т29: текстовият извод на часовника — ЧИСТА функция (unit тествана).
    cells: [{dow, h, med_snr, n}] от реалната история. „Изпрати сега" ако
    текущият час е сред най-добрите (≥ медианата на всички часове);
    иначе „по-добре в HH:00" — следващият час над медианата. Под 7 дни
    историята е честно маркирана като нискодостоверна. now се инжектира
    (frozen NOW в тестове — урокът от Т18)."""
    by_now = {(c["dow"], c["h"]): c for c in cells}
    import datetime as _dt
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    dow_now, h_now = now.isoweekday(), now.hour
    meds = [float(c["med_snr"]) for c in cells if c.get("med_snr") is not None]
    if not meds:
        return {"action": "no_data",
                "text": "Няма достатъчно измервания с SNR — часовникът се учи от историята."}
    med_all = sorted(meds)[len(meds) // 2]
    cur = by_now.get((dow_now, h_now))
    if cur and cur.get("med_snr") is not None and float(cur["med_snr"]) > med_all:
        verdict = {"action": "send_now",
                   "text": f"Изпрати сега — текущият час е над седмичната медиана ({med_all:+.1f} dB)."}
    else:
        # следващият час (по въртене на седмицата) над медианата
        for step in range(1, 25):
            hh = (h_now + step) % 24
            dd = (dow_now + (h_now + step) // 24 - 1) % 7 + 1
            c = by_now.get((dd, hh))
            if c and c.get("med_snr") is not None and float(c["med_snr"]) > med_all:
                verdict = {"action": "better_later",
                           "text": f"По-добре в ~{hh:02d}:00 ч — тогава медианата е {float(c['med_snr']):+.1f} dB (сега {float(cur['med_snr']):+.1f} dB)."
                           if cur and cur.get("med_snr") is not None else
                           f"По-добре в ~{hh:02d}:00 ч — медианата тогава е {float(c['med_snr']):+.1f} dB."}
                break
        else:
            verdict = {"action": "flat",
                       "text": "Няма ясно по-добър час в денонощието — ефирът е равномерен."}
    if days_covered < 7:
        verdict["note"] = (f"Историята покрива ~{days_covered:.1f} дни — "
                           "под 7 дни изводът е с ниска достоверност.")
    return verdict


@router.get("/air-clock")
async def air_clock(request: Request, hours: int = 168,
                    user: CurrentUser = Depends(require_viewer)):
    """Т29: 7×24 решетка — медианен SNR по (ден от седмицата, час) от
    СОБСТВЕНАТА история (events с SNR) + текстов извод. „Измерено, не
    предсказано": само това, което платформата е чула."""
    hours = min(max(hours, 24), 24 * 30)
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT extract(isodow from ts) AS dow, extract(hour from ts) AS h,"
        " percentile_cont(0.5) WITHIN GROUP (ORDER BY (payload->'decoded'->>'snr')::numeric) AS med_snr,"
        " count(*) AS n"
        " FROM events"
        " WHERE ts > now() - make_interval(hours => $1)"
        "   AND payload->'decoded'->>'snr' IS NOT NULL"
        " GROUP BY 1, 2 ORDER BY 1, 2",
        hours)
    days_covered = await pool.fetchval(
        "SELECT extract(epoch from now() - min(ts)) / 86400.0 FROM events"
        " WHERE payload->'decoded'->>'snr' IS NOT NULL")
    cells = [
        {"dow": int(r["dow"]), "h": int(r["h"]),
         "med_snr": float(r["med_snr"]) if r["med_snr"] is not None else None,
         "n": int(r["n"])}
        for r in rows
    ]
    verdict = air_clock_verdict(cells, float(days_covered or 0))
    return {"data": {"hours": hours, "cells": cells,
                     "days_covered": round(float(days_covered or 0), 1),
                     "verdict": verdict}}


@router.get("/waterfall")
async def waterfall(request: Request, hours: int = 168, top: int = 30,
                    user: CurrentUser = Depends(require_viewer)):
    """Т28: матрица връзки×време — цветът е SNR/активност. Ребрата идват от
    NeighborInfo (споделеният _topology_edges — същите, както на Картата);
    кофите — от events per (подател, съсед). Криптираните часове (без
    декодиран SNR, но с трафик от подателя) се връщат като encrypted_only —
    UI ги ЩРИХОВА: „известна неизвестност", не тишина."""
    hours = min(max(hours, 24), 24 * 30)
    grain = "hour" if hours <= 24 else "day"
    pool = request.app.state.pool
    limit = max(1, min(top, 60))
    # двойките идват директно от events (NeighborInfo върви криптирано —
    # виж _topology_edges); топ N по трафик за четлив водопад
    rows = await pool.fetch(
        f"WITH pairs AS ("
        f" SELECT lower(d.external_id) AS sender, lower(nb->>'node') AS neighbor,"
        f" count(*) AS total"
        f" FROM events e JOIN devices d ON d.id = e.device_id"
        f" CROSS JOIN LATERAL jsonb_array_elements(e.payload->'decoded'->'neighbors') AS nb"
        f" WHERE e.ts > now() - make_interval(hours => $1)"
        f"   AND jsonb_typeof(e.payload->'decoded'->'neighbors') = 'array'"
        f"   AND coalesce(nb->>'node','') LIKE '!%'"
        f" GROUP BY 1, 2 ORDER BY 3 DESC LIMIT {limit}"
        f"), per AS ("
        f" SELECT lower(d.external_id) AS sender, lower(nb->>'node') AS neighbor,"
        f" date_trunc('{grain}', e.ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS bucket,"
        f" count(*) AS n,"
        f" round(avg(nullif(nb->>'snr','')::numeric), 1) AS snr"
        f" FROM events e JOIN devices d ON d.id = e.device_id"
        f" CROSS JOIN LATERAL jsonb_array_elements(e.payload->'decoded'->'neighbors') AS nb"
        f" WHERE e.ts > now() - make_interval(hours => $1)"
        f"   AND jsonb_typeof(e.payload->'decoded'->'neighbors') = 'array'"
        f" GROUP BY 1, 2, 3)"
        f" SELECT per.sender, per.neighbor, per.bucket, per.n, per.snr"
        f" FROM per JOIN pairs USING (sender, neighbor)"
        f" ORDER BY per.sender, per.neighbor, per.bucket",
        hours)
    by_edge: dict[tuple, list] = {}
    for r in rows:
        key = (r["sender"], r["neighbor"])
        by_edge.setdefault(key, []).append({
            "t": r["bucket"].isoformat(),
            "n": int(r["n"]),
            "snr": float(r["snr"]) if r["snr"] is not None else None,
        })
    # totals по двойка (от pairs CTE — втори лек проход)
    pair_rows = await pool.fetch(
        f"SELECT lower(d.external_id) AS sender, lower(nb->>'node') AS neighbor,"
        f" count(*) AS total"
        f" FROM events e JOIN devices d ON d.id = e.device_id"
        f" CROSS JOIN LATERAL jsonb_array_elements(e.payload->'decoded'->'neighbors') AS nb"
        f" WHERE e.ts > now() - make_interval(hours => $1)"
        f"   AND jsonb_typeof(e.payload->'decoded'->'neighbors') = 'array'"
        f"   AND coalesce(nb->>'node','') LIKE '!%'"
        f" GROUP BY 1, 2 ORDER BY 3 DESC LIMIT {limit}",
        hours)
    totals: dict[tuple, int] = {}
    for r in pair_rows:
        totals[(r["sender"], r["neighbor"])] = int(r["total"])
    # криптирани часове по подател (пулс-SQL разширение): кофа с трафик, но
    # без нито едно декодируемо съобщение → „известна неизвестност"
    enc_rows = await pool.fetch(
        f"SELECT lower((regexp_match(topic, '(![0-9a-fA-F]+)$'))[1]) AS node,"
        f" date_trunc('{grain}', ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS bucket,"
        f" count(*) FILTER (WHERE packet_type = 'meshtastic-encrypted') AS enc,"
        f" count(*) FILTER (WHERE packet_type <> 'meshtastic-encrypted') AS plain"
        f" FROM packets WHERE topic LIKE 'msh/%'"
        f"   AND ts > now() - make_interval(hours => $1)"
        f" GROUP BY 1, 2 HAVING count(*) FILTER (WHERE packet_type = 'meshtastic-encrypted') > 0",
        hours)
    enc_only = {(r["node"], r["bucket"].isoformat()) for r in enc_rows if r["plain"] == 0}
    out = []
    for (frm, to), total in totals.items():
        cells = by_edge.get((frm, to), [])
        for c in cells:
            c["encrypted_only"] = (frm, c["t"]) in enc_only
        out.append({"from": frm, "to": to, "packets": total,
                    "cells": sorted(cells, key=lambda c: c["t"])})
    return {"data": {"hours": hours, "grain": grain, "edges": out}}


@router.get("/fog")
async def fog(request: Request, hours: int = 168, step: float = 0.02,
              user: CurrentUser = Depends(require_viewer)):
    """Т34: мъгла и следи — осветените клетки (кофична плътност по
    позиционни events). „Никога не чувано" (черно) е клиентски фон;
    бекендът връща само клетките с данни. step в градуси (0.02 ≈ 2 km)."""
    hours = min(max(hours, 1), 24 * 30)
    step = min(max(step, 0.005), 0.5)
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT round((e.payload->'decoded'->>'lat')::numeric / $2) AS gy,"
        " round((e.payload->'decoded'->>'lng')::numeric / $2) AS gx,"
        " count(*) AS n, max(e.ts) AS last,"
        " count(DISTINCT e.device_id) AS nodes,"
        " round(avg((e.payload->'decoded'->>'snr')::numeric), 1) AS snr"
        " FROM events e"
        " WHERE e.ts > now() - make_interval(hours => $1)"
        "   AND e.payload->'decoded'->>'lat' ~ '^-?[0-9]+([.][0-9]+)?$'"
        "   AND e.payload->'decoded'->>'lng' ~ '^-?[0-9]+([.][0-9]+)?$'"
        " GROUP BY 1, 2 ORDER BY 4 DESC LIMIT 4000",
        hours, step)
    cells = [
        {"lat": round((float(r["gy"]) + 0.5) * step, 5),
         "lng": round((float(r["gx"]) + 0.5) * step, 5),
         "n": int(r["n"]), "last": r["last"].isoformat(),
         "nodes": int(r["nodes"]),
         "snr": float(r["snr"]) if r["snr"] is not None else None}
        for r in rows
    ]
    return {"data": {"hours": hours, "step": step, "cells": cells}}


@router.get("/positions")
async def positions(request: Request, hours: int = 24,
                    user: CurrentUser = Depends(require_viewer)):
    """Т35: хронология на позициите за плейбек (node, lat, lng, snr, ts) —
    възходящо по време, кап 4000 реда. Клиентът рендира всеки възел на
    последната му позиция <= T (T = слайдерът)."""
    hours = min(max(hours, 1), 24 * 30)
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT lower(d.external_id) AS node,"
        " (e.payload->'decoded'->>'lat')::numeric AS lat,"
        " (e.payload->'decoded'->>'lng')::numeric AS lng,"
        " (e.payload->'decoded'->>'snr')::numeric AS snr, e.ts"
        " FROM events e JOIN devices d ON d.id = e.device_id"
        " WHERE e.ts > now() - make_interval(hours => $1)"
        "   AND e.payload->'decoded'->>'lat' ~ '^-?[0-9]+([.][0-9]+)?$'"
        "   AND e.payload->'decoded'->>'lng' ~ '^-?[0-9]+([.][0-9]+)?$'"
        " ORDER BY e.ts DESC LIMIT 4000", hours)
    # QA-1 F6: DESC запазва НАЙ-НОВИТЕ 4000 (ASC отрязваше настоящето);
    # клиентът получава възходящо за плейбека
    rows = list(reversed(rows))
    return {"data": {
        "hours": hours,
        "positions": [
            {"node": r["node"], "lat": float(r["lat"]), "lng": float(r["lng"]),
             "snr": float(r["snr"]) if r["snr"] is not None else None,
             "ts": r["ts"].isoformat()}
            for r in rows
        ],
    }}


@router.get("/{device_id}")
async def get_device(device_id: str, request: Request, user: CurrentUser = Depends(require_viewer)):
    r = await request.app.state.pool.fetchrow(
        "SELECT id, protocol, external_id, name, status, metadata, capabilities,"
        " muted, blocked, first_seen_at, last_seen_at FROM devices WHERE id = $1",
        device_id,
    )
    if not r:
        raise HTTPException(status_code=404, detail="not_found")
    return {
        "data": {
            "id": str(r["id"]),
            "protocol": r["protocol"],
            "external_id": r["external_id"],
            "name": r["name"],
            "status": r["status"],
            "muted": r["muted"],
            "blocked": r["blocked"],
            "metadata": json.loads(r["metadata"]),
            "capabilities": json.loads(r["capabilities"]),
            "first_seen_at": r["first_seen_at"].isoformat(),
            "last_seen_at": r["last_seen_at"].isoformat(),
        }
    }


async def _set_flag(request: Request, device_id: str, column: str,
                    value: bool, user, action: str) -> dict:
    if column not in ("muted", "blocked"):
        raise HTTPException(status_code=422, detail="неизвестен флаг")
    pool = request.app.state.pool
    r = await pool.fetchrow(
        f"UPDATE devices SET {column} = $1 WHERE id = $2::uuid"
        " RETURNING id, external_id",
        value, device_id,
    )
    if r is None:
        raise HTTPException(status_code=404, detail="not_found")
    await audit(pool, user, action, "device", str(r["id"]),
                {"external_id": r["external_id"], "value": value})
    return {"data": {"id": str(r["id"]), column: value}}


class HoldBackIn(BaseModel):
    hold_back: bool


@router.post("/{device_id}/hold-back")
async def set_hold_back(device_id: str, body: HoldBackIn, request: Request,
                        user: CurrentUser = Depends(require_operator)):
    """Т26: hold-back на възела — нормалните му доставки се задържат до
    flush („Изпрати сега") или докато приоритетен пакет от него мине."""
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT external_id FROM devices WHERE id = $1", device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    await pool.execute("UPDATE devices SET hold_back = $2 WHERE id = $1",
                       device_id, body.hold_back)
    # Т26: обнови и картата на живо в engine-а (load() я чете само при старт)
    routing = getattr(request.app.state, "routing", None)
    if routing is not None:
        key = row["external_id"].lower()
        if body.hold_back:
            routing._node_hold_back[key] = True
        else:
            routing._node_hold_back.pop(key, None)
    await audit(pool, user, "device.hold_back", "device",
                row["external_id"], {"hold_back": body.hold_back})
    return {"data": {"id": device_id, "hold_back": body.hold_back}}


class PriorityIn(BaseModel):
    routing_priority: str = Field(pattern=r"^(normal|urgent|critical|auto)$")


@router.post("/{device_id}/priority")
async def set_priority(device_id: str, body: PriorityIn, request: Request,
                       user: CurrentUser = Depends(require_operator)):
    """Т24: приоритет на възела — изходящата опашка класира пакетите му
    (urgent/critical изпреварват при backpressure; auto = по съдържание)."""
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "SELECT id, external_id FROM devices WHERE id = $1", device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    await pool.execute(
        "UPDATE devices SET routing_priority = $2 WHERE id = $1",
        device_id, body.routing_priority)
    # Т24 П3: живо обновяване и в engine-а (load() чете картата само при
    # старт — иначе приоритетът влиза в сила чак при рестарт/reload)
    routing = getattr(request.app.state, "routing", None)
    if routing is not None:
        key = row["external_id"].lower()
        if body.routing_priority == "normal":
            routing._node_priority.pop(key, None)
        else:
            routing._node_priority[key] = body.routing_priority
    await audit(pool, user, "device.priority", "device",
                row["external_id"], {"routing_priority": body.routing_priority})
    return {"data": {"id": device_id, "routing_priority": body.routing_priority}}


@router.post("/{device_id}/mute")
async def mute_device(device_id: str, request: Request,
                      user: CurrentUser = Depends(require_admin)):
    """Заглушаване: пакетите на възела не се записват/рутират/известяват."""
    return await _set_flag(request, device_id, "muted", True, user, "device.mute")


@router.post("/{device_id}/unmute")
async def unmute_device(device_id: str, request: Request,
                        user: CurrentUser = Depends(require_admin)):
    return await _set_flag(request, device_id, "muted", False, user, "device.unmute")


@router.post("/{device_id}/block")
async def block_device(device_id: str, request: Request,
                       user: CurrentUser = Depends(require_admin)):
    """Блокиране за защита: като заглушаването, но със защитен смисъл и audit."""
    return await _set_flag(request, device_id, "blocked", True, user, "device.block")


@router.post("/{device_id}/unblock")
async def unblock_device(device_id: str, request: Request,
                         user: CurrentUser = Depends(require_admin)):
    return await _set_flag(request, device_id, "blocked", False, user, "device.unblock")


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    request: Request,
    packets: bool = False,
    user: CurrentUser = Depends(require_admin),
):
    """Изтрива възела и събитията му; с packets=true трие и пакетите по темите
    му (суровината), с цел защита — напр. нежелан тестови възел."""
    pool = request.app.state.pool
    r = await pool.fetchrow(
        "SELECT id, protocol, external_id FROM devices WHERE id = $1", device_id
    )
    if r is None:
        raise HTTPException(status_code=404, detail="not_found")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM events WHERE device_id = $1", r["id"])
            if packets and r["external_id"].startswith("!"):
                # възелът е последният токен на Meshtastic теми
                await conn.execute(
                    "DELETE FROM packets WHERE topic LIKE '%' || $1", r["external_id"])
            elif packets:
                await conn.execute(
                    "DELETE FROM packets WHERE topic LIKE $1", f"{r['external_id']}/%")
            await conn.execute("DELETE FROM devices WHERE id = $1", r["id"])
    await audit(pool, user, "device.delete", "device", str(r["id"]),
                {"external_id": r["external_id"], "packets": packets})
    return {"data": {"deleted": str(r["id"]), "packets_deleted": packets}}


@router.get("/{device_id}/events")
async def device_events(
    device_id: str,
    request: Request,
    limit: int = 50,
    user: CurrentUser = Depends(require_viewer),
):
    limit = min(limit, 200)
    rows = await request.app.state.pool.fetch(
        "SELECT id, ts, event_type, payload FROM events"
        " WHERE device_id = $1 ORDER BY ts DESC LIMIT $2",
        device_id,
        limit,
    )
    return {
        "data": [
            {
                "id": str(r["id"]),
                "ts": r["ts"].isoformat(),
                "event_type": r["event_type"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]
    }
