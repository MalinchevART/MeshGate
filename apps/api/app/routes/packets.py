import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ..bus import bus
from ..ingest.mesh_decode import topic_parts
from ..security import current_user, require_viewer, CurrentUser

router = APIRouter(prefix="/v1/packets", tags=["packets"])


def _packet_row(r) -> dict:
    parts = topic_parts(r["topic"])
    return {
        "id": str(r["id"]),
        "ts": r["ts"].isoformat(),
        "topic": r["topic"],
        "packet_type": r["packet_type"],
        "decode_status": r["decode_status"],
        "payload_size": r["payload_size"],
        "origin": r["origin"],
        "channel": parts["channel"],
        "node": parts["node"],
    }


@router.get("")
async def list_packets(
    request: Request,
    topic: str | None = None,
    packet_type: str | None = None,
    decode_status: str | None = None,
    origin: str | None = None,
    channel: str | None = None,
    node: str | None = None,
    before: str | None = None,
    dedupe: bool = False,
    limit: int = 50,
    user: CurrentUser = Depends(require_viewer),
):
    limit = min(max(limit, 1), 200)
    where = ["TRUE"]
    args: list = []
    if topic:
        args.append(f"%{topic}%")
        where.append(f"topic ILIKE ${len(args)}")  # ILIKE: drill-down по възел с различен регистър
    if packet_type:
        args.append(packet_type)
        where.append(f"packet_type = ${len(args)}")
    if decode_status:
        args.append(decode_status)
        where.append(f"decode_status = ${len(args)}")
    if origin:
        args.append(origin)
        where.append(f"origin = ${len(args)}")
    if channel:
        # Meshtastic логически канал: msh/<регион>/2/e|c|json/<канал>/!<възел>
        args.append(f"%/2/e/{channel}/%")
        a1 = len(args)
        args.append(f"%/2/json/{channel}/%")
        a2 = len(args)
        where.append(f"(topic LIKE ${a1} OR topic LIKE ${a2})")
    if node:
        args.append(f"%/{node}")
        where.append(f"topic LIKE ${len(args)}")
    if before:
        args.append(before)
        where.append(f"ts < ${len(args)}")
    args.append(limit if not dedupe else limit * 3)
    # при dedupe=1 взимаме и payload_text, за да групираме повторенията
    cols = "id, ts, topic, packet_type, decode_status, payload_size, origin"
    if dedupe:
        cols += ", payload_text"
    rows = await request.app.state.pool.fetch(
        f"SELECT {cols} FROM packets WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ${len(args)}",
        *args,
    )
    if dedupe:
        # повтарящи се (еднаква тема+съдържание) се групират в една линия с
        # брой; данните не се трият — това е ПРОГЛЕДЕН филтър
        out, seen = [], {}
        for r in rows:
            k = (r["topic"], r["payload_text"] or f"#{r['id']}")
            if k in seen:
                seen[k]["dup_count"] += 1
                continue
            item = _packet_row(r)
            item["dup_count"] = 1
            seen[k] = item
            out.append(item)
            if len(out) >= limit:
                break
        next_before = None
        return {"data": out, "next_before": next_before}
    next_before = rows[-1]["ts"].isoformat() if len(rows) == limit else None
    return {"data": [_packet_row(r) for r in rows], "next_before": next_before}


@router.get("/{packet_id}/heard")
async def packet_heard(request: Request, packet_id: int,
                       user: CurrentUser = Depends(require_viewer)):
    """Т15 „Двете уши": кой гейт чу ТОЗИ mesh пакет (същият packet_id,
    различни приемници). Автодиагноза — проблемът е възел X, не
    ретранслатора/средата. Сив „Unknown" = приемник без име в регистъра.

    П3: агрегира от packet_heard (ingest записва (packet_id, gateway_id)
    ПРЕДИ дедупа — иначе второто копие от друг гейт се реже и „двете уши"
    е мъртво на живи данни). Пакети от преди деплоя на записа — fallback
    към стария events GROUP BY (само подателят, но не е празно)."""
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT h.gateway_id, r.short_name, r.long_name,"
        " h.first_ts, h.last_ts, h.copies"
        " FROM packet_heard h"
        " LEFT JOIN node_registry r ON r.node_id = lower(h.gateway_id)"
        " WHERE h.packet_id = $1"
        " ORDER BY h.first_ts",
        packet_id)
    if rows:
        return {"data": {
            "packet_id": packet_id,
            "heard_by": [
                {
                    "node": r["gateway_id"],
                    "name": r["short_name"] or r["long_name"],
                    "first_ts": r["first_ts"].isoformat(),
                    "last_ts": r["last_ts"].isoformat(),
                    "copies": r["copies"],
                }
                for r in rows
            ],
        }}
    # fallback: стари пакети без packet_heard редове (пред depлоя)
    rows = await pool.fetch(
        "SELECT e.device_id, d.external_id, d.protocol,"
        " r.short_name, r.long_name,"
        " min(e.ts) AS first_ts, max(e.ts) AS last_ts, count(*) AS copies"
        " FROM events e"
        " JOIN devices d ON d.id = e.device_id"
        " LEFT JOIN node_registry r ON r.node_id = lower(d.external_id)"
        " WHERE e.payload->'decoded'->>'packet_id' = $1::text"
        " GROUP BY e.device_id, d.external_id, d.protocol, r.short_name, r.long_name"
        " ORDER BY first_ts",
        str(packet_id))
    return {"data": {
        "packet_id": packet_id,
        "heard_by": [
            {
                "device_id": str(r["device_id"]),
                "node": r["external_id"],
                "name": r["short_name"] or r["long_name"],
                "protocol": r["protocol"],
                "first_ts": r["first_ts"].isoformat(),
                "copies": r["copies"],
            }
            for r in rows
        ],
    }}


@router.get("/facets")
async def packet_facets(
    request: Request, hours: int = 24,
    user: CurrentUser = Depends(require_viewer),
):
    """Фасети за интуитивна филтрация: брой по тип съобщение, логически
    канал (Bulgaria, Sofia…) и възел (!hex) през последните N часа."""
    hours = min(max(hours, 1), 168)
    rows = await request.app.state.pool.fetch(
        "SELECT topic, packet_type FROM packets"
        " WHERE ts > now() - make_interval(hours => $1)"
        " ORDER BY ts DESC LIMIT 20000",
        hours,
    )
    by_type: dict[str, int] = {}
    by_channel: dict[str, dict] = {}
    by_node: dict[str, dict] = {}
    for r in rows:
        ptype = r["packet_type"] or "unknown"
        by_type[ptype] = by_type.get(ptype, 0) + 1
        parts = topic_parts(r["topic"])
        if parts["channel"]:
            key = parts["channel"]
            ch = by_channel.setdefault(key, {"channel": key, "count": 0,
                                             "types": set()})
            ch["count"] += 1
            ch["types"].add(ptype)
        if parts["node"]:
            key = parts["node"]
            nd = by_node.setdefault(key, {"node": key, "count": 0})
            nd["count"] += 1
    return {"data": {
        "hours": hours,
        "total": len(rows),
        "types": sorted(
            ({"type": k, "count": v} for k, v in by_type.items()),
            key=lambda x: -x["count"]),
        "channels": sorted(
            ({"channel": c["channel"], "count": c["count"],
              "types": sorted(c["types"])} for c in by_channel.values()),
            key=lambda x: -x["count"])[:60],
        "nodes": sorted(by_node.values(), key=lambda x: -x["count"])[:50],
    }}


@router.get("/{packet_id}/delivery")
async def packet_delivery(request: Request, packet_id: str,
                          user: CurrentUser = Depends(require_viewer)):
    """Т16/Т17 Касова бележка: end-to-end статус по packet ред:
    • sent — пакетът Е изход на правило (origin routing:%)
    • uploaded — качен в msh/ (темата му)
    • acked — мрежата върна Routing ACK с request_id = нашия mesh packet id
      (данните: events.payload.decoded.ack_request_id, записани от ингеста)
    • ack_error — ACK с грешка (напр. NO_RESPONSE → „без следа")
    Работи и за криптирани канали — ACK метаданните са видими."""
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "SELECT topic, origin, payload->'decoded'->>'packet_id' AS mesh_pid"
        " FROM packets WHERE id = $1", packet_id)
    if row is None:
        raise HTTPException(404, "няма такъв пакет")
    mesh_pid = row["mesh_pid"]
    ack = None
    if mesh_pid:
        ack = await pool.fetchrow(
            "SELECT e.ts, d.external_id AS from_node,"
            " e.payload->'decoded'->>'ack_error_reason' AS reason"
            " FROM events e JOIN devices d ON d.id = e.device_id"
            " WHERE e.payload->'decoded'->>'ack_request_id' = $1::text"
            " ORDER BY e.ts DESC LIMIT 1", mesh_pid)
    is_sent = (row["origin"] or "").startswith("routing:")
    status = "не-изходен"
    if is_sent and ack:
        status = "acked" if not ack["reason"] else f"ack_error:{ack['reason']}"
    elif is_sent:
        status = "uploaded"
    return {"data": {
        "packet_id": packet_id,
        "mesh_packet_id": mesh_pid,
        "sent": is_sent,
        "status": status,
        "ack_by": ack["from_node"] if ack else None,
        "ack_at": ack["ts"].isoformat() if ack else None,
        "ack_error": ack["reason"] if ack else None,
    }}


@router.get("/{packet_id}")
async def get_packet(packet_id: str, request: Request, user: CurrentUser = Depends(require_viewer)):
    r = await request.app.state.pool.fetchrow(
        "SELECT * FROM packets WHERE id = $1", packet_id
    )
    if not r:
        raise HTTPException(status_code=404, detail="not_found")
    raw = r["payload_raw"]
    trace = await request.app.state.pool.fetch(
        "SELECT ts, decision, topic, reason FROM bridge_events"
        " WHERE topic = $1 ORDER BY ts DESC LIMIT 20",
        r["topic"],
    )
    # човешка обобщена форма за Meshtastic пакета (текст/батерия/позиция/
    # SNR/съседи/маршрут) — суровината си остава в payload_text/hex
    mesh = None
    if r["topic"].startswith("msh/"):
        from ..ingest.mesh_decode import decode_envelope_protobuf, envelope_info
        mesh = envelope_info(r["payload_text"] or "")
        if mesh is None and raw is not None:
            # Т36: пре-декодирането на детайла също ползва PSK картата
            psk = getattr(getattr(request.app.state, "ingest", None), "psk_map", None)
            mesh = decode_envelope_protobuf(bytes(raw), psk)
        if mesh is not None:
            mesh = {k: mesh.get(k) for k in (
                "packet_type", "node_id", "text", "battery", "lat", "lng",
                "snr", "rssi", "packet_id", "neighbors", "route")}
    return {
        "data": {
            **_packet_row(r),
            "payload_text": r["payload_text"],
            "payload_hex": (raw.hex() if raw is not None else None),
            "decode_error": r["decode_error"],
            "decoder_id": r["decoder_id"],
            "mesh": mesh,
            "qos": r["qos"],
            "retain": r["retain"],
            "trace": [
                {
                    "ts": t["ts"].isoformat(),
                    "decision": t["decision"],
                    "reason": t["reason"],
                }
                for t in trace
            ],
        }
    }


@router.post("/export")
async def export_packets(
    body: dict, request: Request, user: CurrentUser = Depends(require_viewer)
):
    limit = min(int(body.get("limit", 1000)), 10000)
    fmt = body.get("format", "json")
    if fmt != "json":
        raise HTTPException(status_code=422, detail="validation_failed: поддържа се json")
    rows = await request.app.state.pool.fetch(
        "SELECT ts, topic, packet_type, decode_status, payload_size, origin, payload_text"
        " FROM packets ORDER BY ts DESC LIMIT $1",
        limit,
    )
    items = [
        {
            "ts": r["ts"].isoformat(),
            "topic": r["topic"],
            "packet_type": r["packet_type"],
            "decode_status": r["decode_status"],
            "payload_size": r["payload_size"],
            "origin": r["origin"],
            "payload_text": r["payload_text"],
        }
        for r in rows
    ]
    return JSONResponse(
        {"data": items},
        headers={"Content-Disposition": f'attachment; filename="packets-export-{limit}.json"'},
    )


@router.websocket("/ws")
async def ws_packets(websocket: WebSocket):
    user = await current_user_from_ws(websocket)
    if user is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    topic_contains = websocket.query_params.get("topic") or None
    packet_type = websocket.query_params.get("packet_type") or None
    q = bus.subscribe()
    try:
        while True:
            get_task = asyncio.create_task(q.get())
            hb_task = asyncio.create_task(asyncio.sleep(15))
            done, pending = await asyncio.wait(
                {get_task, hb_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            if hb_task in done:
                await websocket.send_json({"type": "heartbeat"})
                continue
            event = get_task.result()
            data = event.get("data", {})
            if topic_contains and topic_contains not in data.get("topic", ""):
                continue
            if packet_type and data.get("packet_type") != packet_type:
                continue
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


async def current_user_from_ws(websocket: WebSocket):
    from ..security import resolve_session

    return await resolve_session(
        websocket.app.state.pool, websocket.cookies.get("mg_session")
    )
