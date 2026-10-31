"""Т7 „Критични събития" (docs/16 Етап 3): детектори + фонов evaluator.

Платформата вече брои мъртви букви и провалени известия (лентата на
аномалиите); това е агрегаторът „критично СЕГА" — събития с живот:
open → acked | silenced(до timestamp) → resolved (self-resolve при
изчезнало условие; връщане на условието = нов епизод, occurrences+1).

Детекторите са чисти функции върху редове (unit тестове без БД);
клеъният към данните е CriticalEngine.run_once — тестваем и през
интеграционните тестове (tick през env CRITICAL_TICK_S).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from .config import settings as app_settings

log = logging.getLogger("meshgate.critical")

# прагове по подразбиране; реалните идват от settings ключ 'critical'
DEFAULTS = {"battery_pct": 20, "deadletter_24h": 3, "silence_hours": 12}

SETTINGS_KEY = "critical"


def thresholds(cfg: dict | None) -> dict:
    """Слей настройките от БД с defaults — боклучивите стойности падат."""
    import math
    out = dict(DEFAULTS)
    if isinstance(cfg, dict):
        for k in DEFAULTS:
            try:
                v = cfg.get(k)
                if v is None:
                    continue
                fv = float(v)
                if math.isfinite(fv) and fv >= 0:
                    out[k] = fv
            except (TypeError, ValueError):
                continue  # боклучива стойност → default (defensive, правило №4)
    return out


# ============================================================================
# Детектори — чисти функции
# ============================================================================

@dataclass(frozen=True)
class Detected:
    event_key: str
    kind: str                      # battery | deadletter | silence
    severity: str = "critical"
    payload: dict = field(default_factory=dict)


def detect_battery(rows: Sequence[Any], threshold_pct: float) -> list[Detected]:
    """rows: най-скорошна батерия на възел от events (node, bat, ts).
    Прагът е включващ: равен на прага = критично („под 20%" → <= 20)."""
    out: list[Detected] = []
    for r in rows:
        node, bat = r.get("node"), r.get("bat")
        if not node or bat is None:
            continue
        try:
            if float(bat) <= threshold_pct:
                out.append(Detected(
                    event_key=f"battery:{node}",
                    kind="battery",
                    payload={
                        "node": node,
                        "battery": float(bat),
                        "links": [{"page": "map", "label": "карта"},
                                  {"page": "packets", "params": {"node": node},
                                   "label": "пакети"}],
                    },
                ))
        except (TypeError, ValueError):
            continue
    return out


def detect_deadletter(rows: Sequence[Any], threshold: float) -> list[Detected]:
    """rows: (rule, cnt) от packets тема deadletter/% за 24 ч."""
    out: list[Detected] = []
    for r in rows:
        rule, cnt = r.get("rule"), r.get("cnt")
        if not rule or cnt is None:
            continue
        if int(cnt) >= threshold:
            out.append(Detected(
                event_key=f"deadletter:{rule}",
                kind="deadletter",
                payload={
                    "rule": rule,
                    "deadletter_24h": int(cnt),
                    "links": [{"page": "packets", "params": {"topic": "deadletter/"},
                               "label": "мъртви букви"}],
                },
            ))
    return out


def detect_silence(rows: Sequence[Any], threshold_hours: float,
                   now: datetime | None = None) -> list[Detected]:
    """rows: meshtastic възли (node, last_seen, first_seen, muted, blocked).
    Мълчание = last_seen по-стар от прага; новите възли (по-млади от
    прага) не алармират — урокът от Т18 „канаря": без история няма ритъм."""
    now = now or datetime.now(timezone.utc)
    limit = now - timedelta(hours=threshold_hours)
    out: list[Detected] = []
    for r in rows:
        node = r.get("node")
        last_seen, first_seen = r.get("last_seen"), r.get("first_seen")
        if not node or last_seen is None or first_seen is None:
            continue
        if r.get("muted") or r.get("blocked"):
            continue  # заглушен възел мълчи по желание — не е инцидент
        if first_seen > limit:
            continue  # нов възел — още няма очакван ритъм
        if last_seen < limit:
            silent_h = (now - last_seen).total_seconds() / 3600.0
            out.append(Detected(
                event_key=f"silence:{node}",
                kind="silence",
                severity="important",
                payload={
                    "node": node,
                    "silent_hours": round(silent_h, 1),
                    "last_seen": last_seen.isoformat(),
                    "links": [{"page": "devices", "label": "устройства"},
                              {"page": "map", "label": "карта"}],
                },
            ))
    return out


def canary_threshold_hours(p95_seconds: float | None,
                           base_hours: float) -> float | None:
    """Т18 Канаря: научен ритъм — праг = max(базата, 2.5×p95 интервал).
    None (няма достатъчно история) → само базата; рядко пишещ възел не
    алармира рано (урокът от спеката: „нов възел не алармира")."""
    if p95_seconds is None or p95_seconds <= 0:
        return base_hours
    return max(base_hours, round((p95_seconds * 2.5) / 3600.0, 1))


# ============================================================================
# Преходи на състоянието — чиста функция (unit тествана)
# ============================================================================

def detect_silence_canary(rows: Sequence[Any], base_hours: float,
                          rhythms: dict[str, float],
                          now: datetime | None = None) -> list[Detected]:
    """Канаря-версия на detect_silence: прагът е max(базата, 2.5×p95
    ритъм) per възел; ритъмът влиза в payload („научен ритъм: X мин")."""
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    out: list[Detected] = []
    for r in rows:
        node = r.get("node")
        last_seen, first_seen = r.get("last_seen"), r.get("first_seen")
        if not node or last_seen is None or first_seen is None:
            continue
        if r.get("muted") or r.get("blocked"):
            continue
        thr_h = canary_threshold_hours(rhythms.get(node), base_hours)
        if first_seen > now - timedelta(hours=thr_h):
            continue
        if last_seen < now - timedelta(hours=thr_h):
            silent_h = (now - last_seen).total_seconds() / 3600.0
            payload = {
                "node": node,
                "silent_hours": round(silent_h, 1),
                "last_seen": last_seen.isoformat(),
                "links": [{"page": "devices", "label": "устройства"},
                          {"page": "map", "label": "карта"}],
            }
            p95 = rhythms.get(node)
            if p95:
                payload["rhythm_p95_min"] = round(p95 / 60.0, 1)
            out.append(Detected(
                event_key=f"silence:{node}",
                kind="silence",
                severity="important",
                payload=payload,
            ))
    return out


def plan_transitions(existing: Sequence[dict], detected_keys: set[str],
                     now: datetime) -> dict[str, list[dict]]:
    """Решава upsert/resolve стъпките за един цикъл.

    existing: редове от critical_events (event_key, status, silenced_until).
    Връща {'upsert': [...], 'resolve': [...]} — водещият ги прилага в
    една транзакция. Логика:
    • отсъстващ ключ + open/acked/silenced условие изчезнало → resolved
    • silence изтекъл + условие още налице → open (пак буди оператора)
    • resolved + условие върнало се → reopen (occurrences+1)
    """
    by_key = {r["event_key"]: r for r in existing}
    upsert: list[dict] = []
    resolve: list[dict] = []
    for key in detected_keys:
        row = by_key.get(key)
        if row is None:
            continue  # новите се вмъкват от run_once директно
        if row.get("status") == "resolved":
            upsert.append({"event_key": key, "action": "reopen"})
        elif row.get("status") == "silenced":
            until = row.get("silenced_until")
            if until is not None and until <= now:
                upsert.append({"event_key": key, "action": "wake"})  # изтекъл silence
            else:
                upsert.append({"event_key": key, "action": "refresh"})
        else:
            upsert.append({"event_key": key, "action": "refresh"})
    for r in existing:
        key, status = r["event_key"], r.get("status")
        if status == "resolved" or key in detected_keys:
            continue
        resolve.append({"event_key": key})  # условието изчезнало → resolved
    return {"upsert": upsert, "resolve": resolve}


# ============================================================================
# Engine — фонов работник по шаблона на NotificationEngine
# ============================================================================

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Т35: разстояние в метри (haversine; достатъчно за км-радиуси)."""
    import math
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def detect_geofence(rows: Sequence[Any], zones: list[dict]) -> list[Detected]:
    """Т35: „възел напусна зоната" — последната позиция ИЗВЪН радиуса И
    предходна позиция ВЪТРЕ (преход вътре→извън). Зона с node="*" важи за
    всички. Един event на (зона, възел). rows: [{node, ts, lat, lng}]
    подредени DESC по ts (първите 2 на възел са преходът)."""
    by_node: dict[str, list[dict]] = {}
    for r in rows:
        by_node.setdefault(r["node"], []).append(r)
    out: list[Detected] = []
    seen: set[tuple[str, str]] = set()
    for z in zones or []:
        try:
            zlat, zlng = float(z["lat"]), float(z["lng"])
            radius = float(z["radius_m"])
            if radius <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        zname = str(z.get("name") or "зона")
        scope = str(z.get("node") or "*").lower()
        for node, positions in by_node.items():
            if scope != "*" and scope != node:
                continue
            if len(positions) < 2:
                continue  # няма преход вътре→извън
            if (zname, node) in seen:
                continue
            last, prev = positions[0], positions[1]
            d_last = haversine_m(last["lat"], last["lng"], zlat, zlng)
            d_prev = haversine_m(prev["lat"], prev["lng"], zlat, zlng)
            if d_last > radius < d_prev:
                continue  # и двете извън (или и двете вътре) — няма преход
            if d_last > radius and d_prev <= radius:
                seen.add((zname, node))
                out.append(Detected(
                    event_key=f"geofence:{zname}:{node}",
                    kind="geofence",
                    severity="important",
                    payload={
                        "node": node, "zone": zname,
                        "distance_m": round(d_last),
                        "radius_m": round(radius),
                    }))
    return out


class CriticalEngine:
    """Префеизчислява критичните събития на всеки tick и materialализира
    състоянието в critical_events. Рестарт-безопасен: състоянието е
    изцяло в БД; пропуснат цикъл само забавя с ≤tick."""

    def __init__(self, pool):
        self.pool = pool
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.last_run_at: datetime | None = None
        self.last_error: str | None = None
        self.cycles = 0

    # ---- настройки -------------------------------------------------------
    async def _thresholds(self) -> dict:
        row = await self.pool.fetchrow(
            "SELECT value FROM settings WHERE key = $1", SETTINGS_KEY)
        cfg = None
        if row is not None:
            try:
                cfg = json.loads(row["value"]) if isinstance(row["value"], str) \
                    else row["value"]
            except (json.JSONDecodeError, TypeError):
                cfg = None
        return thresholds(cfg)

    # ---- данни за детекторите ---------------------------------------------
    async def _battery_rows(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT DISTINCT ON (e.payload->'decoded'->>'node')"
            " (e.payload->'decoded'->>'node') AS node,"
            " (e.payload->'decoded'->>'battery')::numeric AS bat"
            " FROM events e"
            " WHERE e.ts > now() - interval '24 hours'"
            "   AND e.payload->'decoded'->>'battery' IS NOT NULL"
            " ORDER BY node, e.ts DESC")
        return [dict(r) for r in rows]

    async def _deadletter_rows(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT split_part(topic, '/', 2) AS rule, count(*) AS cnt"
            " FROM packets WHERE topic LIKE 'deadletter/%'"
            "   AND ts > now() - interval '24 hours'"
            " GROUP BY 1")
        return [dict(r) for r in rows]

    async def _silence_rows(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT external_id AS node, last_seen_at AS last_seen,"
            " first_seen_at AS first_seen, muted, blocked"
            " FROM devices WHERE protocol = 'meshtastic'"
            "   AND external_id LIKE '!%'")
        out = []
        for r in rows:
            d = dict(r)
            out.append(d)
        return out

    async def _rhythms(self, nodes: list[str]) -> dict[str, float]:
        """p95 на интервалите (сек) за възлите-кандидати, 7 д история;
        възли с <20 АКТИВНИ ЧАСА нямат ритъм (None).
        Pulse-моделът (урокът от миграция 009): стъпка 1 групира по
        (тема, час) върху частичния индекс — НЕ сканира милиони events."""
        if not nodes:
            return {}
        rows = await self.pool.fetch(
            "WITH per AS ("
            " SELECT topic, date_trunc('hour', ts) AS h FROM packets"
            " WHERE topic LIKE 'msh/%' AND ts > now() - interval '7 days'"
            " GROUP BY topic, 2"
            "), n AS ("
            " SELECT lower((regexp_match(topic, '(![0-9a-fA-F]+)$'))[1]) AS node, h"
            " FROM per WHERE (regexp_match(topic, '(![0-9a-fA-F]+)$'))[1] IS NOT NULL"
            "), f AS ("
            " SELECT node, h, lag(h) OVER (PARTITION BY node ORDER BY h) AS prev"
            " FROM n WHERE node = ANY($1::text[]))"
            " SELECT node, count(*) AS n,"
            "  percentile_cont(0.95) WITHIN GROUP"
            "   (ORDER BY extract(epoch FROM h - prev)) AS p95"
            " FROM f WHERE prev IS NOT NULL GROUP BY node HAVING count(*) >= 20",
            nodes)
        return {r["node"]: float(r["p95"]) for r in rows if r["p95"] is not None}

    async def _geofence_rows(self, hours: int = 48) -> list[dict]:
        """Последните 2 позиции на всеки възел с числова позиция — входът на
        detect_geofence (прехода вътре→извън в прозореца)."""
        rows = await self.pool.fetch(
            "SELECT node, ts, lat, lng FROM ("
            " SELECT lower(d.external_id) AS node, e.ts,"
            "  (e.payload->'decoded'->>'lat')::numeric AS lat,"
            "  (e.payload->'decoded'->>'lng')::numeric AS lng,"
            "  row_number() OVER (PARTITION BY lower(d.external_id) ORDER BY e.ts DESC) AS rn"
            " FROM events e JOIN devices d ON d.id = e.device_id"
            " WHERE e.ts > now() - make_interval(hours => $1)"
            "   AND e.payload->'decoded'->>'lat' ~ '^-?[0-9]+([.][0-9]+)?$'"
            "   AND e.payload->'decoded'->>'lng' ~ '^-?[0-9]+([.][0-9]+)?$'"
            ") t WHERE rn <= 2 ORDER BY node, ts DESC", hours)
        return [
            {"node": r["node"], "ts": r["ts"],
             "lat": float(r["lat"]), "lng": float(r["lng"])}
            for r in rows
        ]

    # ---- един цикъл (тестваем вход) ---------------------------------------
    async def run_once(self) -> dict:
        cfg = await self._thresholds()
        # Т18 канаря: за мълчаливите над базовия праг — научи собствения
        # ритъм (p95 на интервалите, 7 д) и алармирай САМО над 2.5×ритъм
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        silence_rows = await self._silence_rows()
        base_lim = _dt.now(_tz.utc) - _td(hours=cfg["silence_hours"])
        cand = sorted({r.get("node") for r in silence_rows
                       if r.get("last_seen") is not None
                       and r.get("first_seen") is not None
                       and r.get("last_seen") < base_lim
                       and not r.get("muted") and not r.get("blocked")})
        if not hasattr(self, "_rhythms_at") or                 (datetime.now(timezone.utc) - self._rhythms_at).total_seconds() > 600:
            self._rhythms = await self._rhythms(cand) if cand else {}
            self._rhythms_at = datetime.now(timezone.utc)
        rhythms = self._rhythms
        # Т35: зони от settings 'geofence' (празни/боклучиви — без детекция);
        # evaluator-ът чете settings на всеки цикъл → живо без рестарт
        gz_row = await self.pool.fetchrow("SELECT value FROM settings WHERE key='geofence'")
        zones: list[dict] = []
        if gz_row is not None:
            try:
                zones = json.loads(gz_row["value"]) if isinstance(gz_row["value"], str) else gz_row["value"]
            except (json.JSONDecodeError, TypeError):
                zones = []
        gf_rows = await self._geofence_rows() if zones else []
        detected = (
            detect_battery(await self._battery_rows(), cfg["battery_pct"])
            + detect_deadletter(await self._deadletter_rows(), cfg["deadletter_24h"])
            + detect_silence_canary(silence_rows, cfg["silence_hours"], rhythms)
            + detect_geofence(gf_rows, zones)
        )
        detected_keys = {d.event_key for d in detected}
        now = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                existing = [
                    dict(r) for r in await conn.fetch(
                        "SELECT event_key, status, silenced_until"
                        " FROM critical_events WHERE status <> 'resolved'")
                ]
                resolved_rows = [
                    dict(r) for r in await conn.fetch(
                        "SELECT event_key, status, silenced_until"
                        " FROM critical_events WHERE status = 'resolved'"
                        "   AND event_key = ANY($1::text[])",
                    list(detected_keys) or ["-"],
                )]
                plan = plan_transitions(existing + resolved_rows, detected_keys, now)

                for d in detected:
                    # нов → insert; стар (вкл. resolved) → само payload/last_seen;
                    # статусът се мени от plan стъпките (reopen/wake) подолу
                    await conn.execute(
                        "INSERT INTO critical_events (event_key, kind, severity,"
                        " payload, status, first_seen_at, last_seen_at)"
                        " VALUES ($1,$2,$3,$4::jsonb,'open',$5,$5)"
                        " ON CONFLICT (event_key) DO NOTHING",
                        d.event_key, d.kind, d.severity,
                        json.dumps(d.payload, ensure_ascii=False), now)
                    await conn.execute(
                        "UPDATE critical_events SET payload = $2::jsonb,"
                        " last_seen_at = $3, updated_at = $3 WHERE event_key = $1",
                        d.event_key, json.dumps(d.payload, ensure_ascii=False), now)

                for step in plan["upsert"]:
                    key = step["event_key"]
                    if step["action"] == "reopen":
                        await conn.execute(
                            "UPDATE critical_events SET status='open', resolved_at=NULL,"
                            " acked_by=NULL, acked_at=NULL, silenced_until=NULL,"
                            " occurrences = occurrences + 1, last_seen_at=$2,"
                            " updated_at=$2 WHERE event_key=$1", key, now)
                    elif step["action"] == "wake":
                        await conn.execute(
                            "UPDATE critical_events SET status='open',"
                            " silenced_until=NULL, last_seen_at=$2, updated_at=$2"
                            " WHERE event_key=$1", key, now)
                    # refresh: вече направен горе с payload/last_seen

                for step in plan["resolve"]:
                    await conn.execute(
                        "UPDATE critical_events SET status='resolved', resolved_at=$2,"
                        " updated_at=$2 WHERE event_key=$1 AND status <> 'resolved'",
                        step["event_key"], now)

        self.last_run_at = now
        self.last_error = None
        self.cycles += 1
        return {"detected": len(detected), "kinds": {
            k: sum(1 for d in detected if d.kind == k)
            for k in ("battery", "deadletter", "silence", "geofence")}}

    # ---- живот ------------------------------------------------------------
    def start(self) -> None:
        tick = float(getattr(app_settings(), "critical_tick_s", 30) or 30)
        self._task = asyncio.create_task(self._loop(tick), name="critical")

    async def _loop(self, tick: float) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # worker никога не умира тихо завинаги
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("critical: цикълът гръмна (%s)", self.last_error)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=tick)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
