"""Т8 „Dashboard агрегати: бекенд" (docs/16 Етап 3, F7/F15): ЕДНО GET носи
целия дашборд — KPI ред + кофи за трафика + изпратени 24ч по 3-ч кофи +
канален пончик. Изводимо от packets/devices/critical_events при всяка
заявка; нула материализация, нула миграция, нула фонов процес.

Консистентност ПО КОНСТРУКЦИЯ (не по обещание):
  · traffic[] == stats/overview.buckets[] — същата SQL + споделен
    _fill_hour_buckets (meta.py);
  · kpi.alarms.open == critical-events counts.alarm == шел-чипът — същата
    SQL върху critical_events;
  · kpi.rf == len(/v1/devices/topology.edges) — споделеният
    _topology_edges helper;
  · sent_24h.failed(сума) == мъртвите букви на /v1/anomalies за 24ч —
    същият източник (тема deadletter/%), без кап.
„Изпратени" се брои от origin маркера на препращанията (routing:%) към
локалния брокер — routing_executions НЕ се ползва: подрязва се до
200/правило при рестарт (service.py EXEC_KEEP_PER_RULE).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from ..security import CurrentUser, require_viewer
from .devices import _topology_edges
from .meta import _fill_hour_buckets

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])

STABLE_SNR_DB = -8.0   # == прагът на Т9-pre; ехо-ва в отговора


def _fill_sent_buckets(rows: list) -> list:
    """8 кофи по 3 часа (стени 00/03/06… UTC), запълнени с нули; последната
    съдържа сега."""
    now = datetime.now(timezone.utc)
    wall = now.replace(minute=0, second=0, microsecond=0)
    base = wall - timedelta(hours=(wall.hour % 3))
    got = {r["bucket"].isoformat(): r for r in rows}
    out = []
    for i in range(7, -1, -1):
        b = base - timedelta(hours=3 * i)
        r = got.get(b.isoformat())
        out.append({
            "bucket": b.isoformat(),
            "sent": (r["sent"] if r else 0) or 0,
            "failed": (r["failed"] if r else 0) or 0,
        })
    return out


@router.get("")
async def dashboard(request: Request, hours: int = 24,
                    user: CurrentUser = Depends(require_viewer)):
    pool = request.app.state.pool
    hours = min(max(hours, 1), 168)

    # --- 3.1 трафик (същата SQL като stats/overview) ----------------------
    rows = await pool.fetch(
        "SELECT date_trunc('hour', ts) AS h, count(*) AS n FROM packets"
        " WHERE ts > now() - make_interval(hours => $1) GROUP BY 1 ORDER BY 1",
        hours,
    )
    counts = {r["h"].isoformat(): r["n"] for r in rows}
    traffic = _fill_hour_buckets(counts, hours)
    total = sum(b["count"] for b in traffic)
    last_hour = traffic[-2]["count"] if len(traffic) >= 2 else 0

    # --- 3.2 активни възли (глобален DISTINCT — похватът на pulse) --------
    # --- 3.3 канален пончик (split_part върху ~сотнинте ГРУПИ теми) -------
    active_nodes = await pool.fetchval(
        "WITH per AS ("
        "  SELECT topic FROM packets"
        "  WHERE topic LIKE 'msh/%' AND ts > now() - make_interval(hours => $1)"
        "  GROUP BY topic"
        ") SELECT count(DISTINCT lower((regexp_match(topic, '(![0-9a-fA-F]+)$'))[1]))"
        " FROM per",
        min(hours, 24))
    chan_rows = await pool.fetch(
        "WITH per AS ("
        "  SELECT topic, count(*) AS n FROM packets"
        "  WHERE topic LIKE 'msh/%' AND ts > now() - make_interval(hours => $1)"
        "  GROUP BY topic"
        ") SELECT split_part(topic, '/', 5) AS chan, sum(n)::int AS cnt"
        " FROM per WHERE split_part(topic, '/', 5) <> ''"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 12",
        min(hours, 24))
    channels = [{"name": r["chan"], "count": r["cnt"]} for r in chan_rows]
    total_nodes = await pool.fetchval(
        "SELECT count(*) FROM devices"
        " WHERE protocol = 'meshtastic' AND external_id LIKE '!%'")

    # --- 3.4 изпратени 24ч (фини кофи по 3ч; прозорецът е ФИКСИРАН) --------
    sent_rows = await pool.fetch(
        "SELECT date_trunc('hour', ts)"
        "         - make_interval(hours => (extract(hour FROM ts)::int % 3)) AS bucket,"
        "       count(*) FILTER (WHERE origin LIKE 'routing:%'"
        "                           AND topic NOT LIKE 'deadletter/%') AS sent,"
        "       count(*) FILTER (WHERE topic LIKE 'deadletter/%') AS failed"
        " FROM packets"
        " WHERE ts > now() - interval '24 hours'"
        "   AND (origin LIKE 'routing:%' OR topic LIKE 'deadletter/%')"
        " GROUP BY 1 ORDER BY 1")
    sent_24h = _fill_sent_buckets([dict(r) for r in sent_rows])

    # --- 3.5 аларми (същата SQL като critical counts) ---------------------
    alarm_rows = await pool.fetch(
        "SELECT status, count(*) AS n FROM critical_events"
        " WHERE last_seen_at > now() - make_interval(hours => 24) GROUP BY 1")
    alarm_counts = {r["status"]: r["n"] for r in alarm_rows}

    # --- 3.6 RF връзки (споделеният helper на картата) --------------------
    edges = await _topology_edges(pool, min(hours, 24))
    stable = sum(1 for e in edges
                 if (e["snr_avg"] if e["snr_avg"] is not None else -99) >= STABLE_SNR_DB)

    return {"data": {
        "hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpi": {
            "windows": {"nodes": min(hours, 24), "rf": min(hours, 24),
                        "alarms": 24, "sent": 24},
            "nodes": {"active": active_nodes, "total": total_nodes},
            "packets": {
                "total": total,
                "per_hour": round(total / hours, 1) if hours else 0,
                "last_hour": last_hour,
            },
            "rf": {
                "links": len(edges),
                "stable": stable,
                "stable_snr_db": STABLE_SNR_DB,
                "nodes": len({e["from"] for e in edges} | {e["to"] for e in edges}),
            },
            "alarms": {"open": alarm_counts.get("open", 0)},
        },
        "traffic": traffic,
        "sent_24h": sent_24h,
        "channels": channels,
    }}
