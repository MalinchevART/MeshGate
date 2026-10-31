"""Мета-информация за UI-то: план на функционалностите (кое кога), самостоятелни
проверки (selftest) и обобщени статистики за мониторинг графики."""

import json

from fastapi import APIRouter, Depends, Request

from ..security import CurrentUser, require_viewer

router = APIRouter(prefix="/v1", tags=["meta"])


# ---------- план: дърво на функционалностите (поддържа се от собственика) ----------

PLAN = {
    "title": "MeshGate — план на функционалностите",
    "updated": "2026-10-16",
    "phases": [
        {
            "id": "p0", "title": "Фаза 0 — Основа", "status": "done", "when": "готово (14.10)",
            "items": [
                {"title": "MQTT брокер (EMQX 5.8.8) с потребители и права (ACL)", "status": "done"},
                {"title": "Приемане и запис на всички съобщения (packets/events/devices)", "status": "done"},
                {"title": "Инсталатор с двойен клик + управленско меню + демо възли", "status": "done"},
                {"title": "Резервно копие / възстановяване", "status": "done"},
            ],
        },
        {
            "id": "p1", "title": "Фаза 1 — Конзола", "status": "done", "when": "готово (15.10)",
            "items": [
                {"title": "Пълни екрани: Broker, Profiles (версии+потвърждение), System & Security", "status": "done"},
                {"title": "Мостове към външни брокери + тест на правила + SSRF защита", "status": "done"},
                {"title": "Начална парола P@sswordG@te + банер и смяна от UI/менюто", "status": "done"},
            ],
        },
        {
            "id": "p2", "title": "Фаза 2 — Routing Rules (R1)", "status": "done", "when": "готово (16.10)",
            "items": [
                {"title": "Двигател за правила с пълен журнал на решенията (trace)", "status": "done"},
                {"title": "Шаблони + wizard 5 стъпки + dry-run тест без публикуване", "status": "done"},
                {"title": "Версии с rollback, броячи, права по роли, защита от цикли", "status": "done"},
            ],
        },
        {
            "id": "p25", "title": "Фаза 2.5 — Интуитивност и мониторинг", "status": "done", "when": "готово (16.10)",
            "items": [
                {"title": "Помощник за правила без знание на MQTT (цел → канал → аларма)", "status": "done"},
                {"title": "Мониторинг: графики на трафика, канали, батерии, активност на правилата", "status": "done"},
                {"title": "План & Тестове: дърво на функционалностите + авто-проверки + чеклист", "status": "done"},
                {"title": "First-run съветник: смяна на паролата + разходка из секциите", "status": "done"},
            ],
        },
        {
            "id": "p3", "title": "Фаза 3a — Meshtastic на живо", "status": "done", "when": "готово (16.10, docs/10)",
            "items": [
                {"title": "Детектор по тема msh/+/# + JSON декодер (тип пакет, възел !hex, канал)", "status": "done"},
                {"title": "Емулатор v2: демо възлите генерират Meshtastic съобщения (msh/.../2/e/LongFast/!hex)", "status": "done"},
                {"title": "Meshtastic каналите се показват сами в Помощника и Мониторинга (+ батерии)", "status": "done"},
                {"title": "Семантичен селектор в редактора: мачни по регион/канал/устройство, цветни токени", "status": "done"},
                {"title": "Правило → блок-диаграма (R3.1, визията от MeshGate.docx)", "status": "done"},
                {"title": "Протobuf декодер (бинарни envelopes: текст/батерия/позиция/SNR) + дедупликация по packet id (3b)", "status": "done"},
                {"title": "Топология от NeighborInfo/Routing пакети (3b остатък)", "status": "later"},
            ],
        },
        {
            "id": "p31", "title": "R3 — Правилата като диаграма (визията от MeshGate.docx)", "status": "active", "when": "R3.1 готово; следва R3.2 (виж docs/11)",
            "items": [
                {"title": "Read-only блок-диаграма на всяко правило (Source→Filters→Transform→Destinations)", "status": "done"},
                {"title": "Пълен drag-drop канвас редактор с palette/properties/test (R3.2, React Flow)", "status": "later"},
                {"title": "Router/Branch блок и много изходи (R3.3)", "status": "later"},
            ],
        },
        {
            "id": "p4", "title": "R2 — Входящи мостове + надеждност", "status": "active", "when": "inbound готово (16.10); останалото — следващо",
            "items": [
                {"title": "Входящи мостове: внасят от външен брокер (дедупликация, rate limit, ехо-защита, confirm)", "status": "done"},
                {"title": "Правилата рутират и входящи съобщения, без връщане към същия мост", "status": "done"},
                {"title": "Така се закачат двата публични Meshtastic брокера за тест", "status": "done"},
                {"title": "Повторни опити, dead-letter, метрики per правило, webhook дестинации", "status": "next"},
            ],
        },
        {
            "id": "p5", "title": "Фаза 5 — Известия и автоматизация", "status": "active", "when": "първи срез готов (17.10): Telegram/имейл/webhook",
            "items": [
                {"title": "Известия по тема → Telegram, имейл (SMTP), webhook (docs/12, ADR-006)", "status": "done"},
                {"title": "WhatsApp (CallMeBot); шаблони per канал; тихи часове", "status": "later"},
                {"title": "n8n / Node-RED връзка; Home Assistant + Zigbee2MQTT", "status": "later"},
            ],
        },
        {
            "id": "p6", "title": "Фаза 6 — MeshCore + зрялост", "status": "later", "when": "накрая",
            "items": [
                {"title": "MeshCore адаптер (по документиран протокол); мост Meshtastic↔MeshCore по съвпадащи канали", "status": "later"},
                {"title": "Документация за краен потребител, ъпгрейд миграции", "status": "later"},
            ],
        },
    ],
}


@router.get("/plan")
async def get_plan(request: Request, user: CurrentUser = Depends(require_viewer)):
    return {"data": PLAN}


# ---------- самостоятелни проверки: какво да тества собственикът (авто + ръчно) ----------

MANUAL_CHECKS = [
    {
        "id": "m-login", "title": "Вход и начална парола",
        "steps": "Влез с admin / P@sswordG@te. Трябва да се покаже жълт банер за смяна на паролата.",
        "expected": "Банерът изчезва след смяна (🔑 горе вдясно или от System & Security).",
    },
    {
        "id": "m-live", "title": "Демо възлите пращат живи данни",
        "steps": "Отвори Overview и Packet Explorer (без презареждане).",
        "expected": "Съобщенията от mesh/emul/... пристигат в момента; броячите растат.",
    },
    {
        "id": "m-rule-create", "title": "Правило от шаблон (без знание на MQTT)",
        "steps": "Routing Rules → Помощник → „Аларма при ниска батерия“ → избери канал телеметрия → батерия под 20 → Запази и публикувай → Включи сега.",
        "expected": "Правилото се появява включено; в журнала (🕘) всяко съобщение носи причина.",
    },
    {
        "id": "m-alarm", "title": "Алармите наистина излизат",
        "steps": "Изчакай ~10 сек след включването и отвори Packet Explorer с филтър alerts/.",
        "expected": "Появяват се алармени съобщения alerts/battery/<възел> (батериите на демо възлите са ниски, за да се вижда).",
    },
    {
        "id": "m-versions", "title": "Версии и връщане назад",
        "steps": "Редактирай правилото (промени прага) → Публикувай версия → отвори ⎌ → върни v1.",
        "expected": "След rollback алармите отново следват стария праг.",
    },
    {
        "id": "m-disable", "title": "Изключването спира правилото",
        "steps": "Натисни статуса на правилото (изключено) и изчакай 30 сек.",
        "expected": "Няма нови аларми; в Мониторинг трафикът по alerts/ спада до нула.",
    },
    {
        "id": "m-monitor", "title": "Мониторинг графики",
        "steps": "Отвори страницата Мониторинг.",
        "expected": "Графика на трафика за 24 ч, най-активни канали, батерии на възлите с цветове, активност на правилата.",
    },
    {
        "id": "m-pub-broker", "title": "Публичен Meshtastic брокер (за по-късно)",
        "steps": "Bridges & Routes -> създай мост: посока ВХОДЯЩ, хост mqtt.meshtastic.org, порт 1883, потребител+парола (брокерът изисква акаунт — сложи своите), topic_map: msh/EU_868 -> msh/EU_868 -> включи с потвърждение.",
        "expected": "След ~30 сек в Мониторинг се появяват реални канали Meshtastic EU_868 — LongFast с истински възли; повторните копия се групират (xN в Packet Explorer с отметката за повторения).",
    },
    {
        "id": "m-two-brokers", "title": "Два публични брокера — кръстосана дедупликация (за по-късно)",
        "steps": "Добави втори входящ мост към друг публичен брокер със същия регион/канал. Създай правило канал -> друг брокер от Помощника.",
        "expected": "Едно съобщение, донесено от двата брокера, влиза веднъж (брояч deduped на втория мост расте) и НЕ се препраща втори път към другия брокер.",
    },
    {
        "id": "m-backup", "title": "Резервно копие",
        "steps": "Стартирай deploy/meshgate.cmd → Backup; после Restore от същия файл.",
        "expected": "След restore правилата и потребителите са налице.",
    },
]


@router.get("/selftest")
async def selftest(request: Request, user: CurrentUser = Depends(require_viewer)):
    """Автоматични проверки на живия стек — какво вижда собственикът като ✓/✗."""
    app = request.app
    pool = app.state.pool
    checks: list[dict] = []

    async def add(cid: str, title: str, fn) -> None:
        try:
            status, detail = await fn()
        except Exception as exc:
            status, detail = "fail", str(exc)[:200]
        checks.append({"id": cid, "title": title, "status": status, "detail": detail})

    async def c_db():
        await pool.fetchval("SELECT 1")
        return "ok", "PostgreSQL отговаря"

    async def c_broker():
        st = await app.state.adapter.status()
        return ("ok", f"EMQX жив: {st.get('connections', '?')} връзки") if st else ("fail", "без данни")

    async def c_ingest():
        ing = app.state.ingest
        if ing.healthy:
            return "ok", "приемникът е свързан с брокера"
        return "fail", "приемникът НЕ е свързан"

    async def c_traffic():
        row = await pool.fetchrow("SELECT max(ts) AS last, count(*) AS n FROM packets")
        if not row or row["n"] == 0:
            return "warn", "няма записани съобщения (пусни демо възлите от менюто)"
        age_min = (await pool.fetchval("SELECT extract(epoch from now() - max(ts))/60 FROM packets"))
        if age_min is None or age_min > 5:
            return "warn", f"последното съобщение е отпреди {age_min and round(age_min)} мин"
        return "ok", f"трафик в момента (последно преди {round(age_min * 60)} сек)"

    async def c_routing():
        total = await pool.fetchval("SELECT count(*) FROM routing_rules")
        enabled = await pool.fetchval("SELECT count(*) FROM routing_rules WHERE enabled")
        loaded = len(app.state.routing.rules)
        if enabled != loaded:
            return "warn", f"включени {enabled}, но двигателят е заредил {loaded}"
        if not total:
            return "warn", "няма правила — създай едно от Помощника"
        return "ok", f"{total} правила ({enabled} включени), двигателят ги е заредил"

    async def c_bridges():
        rows = await pool.fetch(
            "SELECT name, health FROM bridge_configs WHERE enabled"
        )
        if not rows:
            return "ok", "няма активни мостове (ok за локална работа)"
        down = [r["name"] for r in rows if r["health"] == "down"]
        if down:
            return "warn", f"недостъпни мостове: {', '.join(down)}"
        return "ok", f"{len(rows)} активен(и) мост(а) — здрави"

    async def c_password():
        from ..security import uses_default_password

        if await uses_default_password(pool):
            return "warn", "admin все още ползва НАЧАЛНАТА парола — смени я"
        return "ok", "началната парола е сменена"

    await add("db", "База данни", c_db)
    await add("broker", "MQTT брокер", c_broker)
    await add("ingest", "Приемник на съобщения", c_ingest)
    await add("traffic", "Трафик в момента", c_traffic)
    await add("routing", "Правила за рутиране", c_routing)
    await add("bridges", "Мостове към външни брокери", c_bridges)
    await add("password", "Парола на администратора", c_password)
    return {"data": {"auto": checks, "manual": MANUAL_CHECKS}}


# ---------- статистики за мониторинг графики ----------

def _family(topic: str) -> str:
    """Групира теми по канал: ID-подобните токени (вкл. Meshtastic !hex) стават '*'."""
    import re

    def idlike(t: str) -> bool:
        return bool(
            t.startswith("!")  # Meshtastic node id
            or re.match(r"^(node|dev|emu|n)\d", t, re.I)
            or (re.match(r"^[0-9a-f-]{4,}$", t, re.I) and "-" in t)
            or (re.match(r"^\d+$", t) and t not in ("1", "2"))  # 1/2 са Meshtastic константи
        )

    return "/".join("*" if idlike(t) else t for t in topic.split("/"))


@router.get("/names")
async def node_names(request: Request, user: CurrentUser = Depends(require_viewer)):
    """Т36: карта !hex → {short, long} от регистъра. Клиентът я кешира и
    показва ИМЕТО навсякъде първо; ID-то е второстепенно (за човека)."""
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT node_id, short_name, long_name FROM node_registry"
        " WHERE short_name IS NOT NULL OR long_name IS NOT NULL")
    return {"data": {
        r["node_id"]: {"short": r["short_name"], "long": r["long_name"]}
        for r in rows
    }}


@router.get("/anomalies")
async def anomalies(
    request: Request, hours: int = 24, user: CurrentUser = Depends(require_viewer)
):
    """Лента на аномалии (docs/15 Вълна 1): случилите се СЪБИТИЯ върху
    оста на времето — мъртви букви, изпратени/провалени известия,
    публикувани версии на правила. За маркерите върху графиките."""
    pool = request.app.state.pool
    hours = min(max(hours, 1), 168)
    out: list[dict] = []
    dl = await pool.fetch(
        "SELECT ts, split_part(topic, '/', 2) AS ref FROM packets"
        " WHERE topic LIKE 'deadletter/%' AND ts > now() - make_interval(hours => $1)"
        " ORDER BY ts DESC LIMIT 200",
        hours,
    )
    for r in dl:
        out.append({"ts": r["ts"].isoformat(), "kind": "deadletter",
                    "label": f"мъртва буква: {r['ref']}"})
    notif = await pool.fetch(
        "SELECT l.ts, l.status, coalesce(c.name, 'канал?') AS name"
        " FROM notification_log l LEFT JOIN notification_channels c"
        "   ON c.id = l.channel_id"
        " WHERE l.status IN ('sent','failed')"
        "   AND l.ts > now() - make_interval(hours => $1)"
        " ORDER BY l.ts DESC LIMIT 200",
        hours,
    )
    for r in notif:
        out.append({"ts": r["ts"].isoformat(),
                    "kind": f"notify_{r['status']}",
                    "label": f"известие {r['status']}: {r['name']}"})
    pubs = await pool.fetch(
        "SELECT ts, entity_id FROM audit_log"
        " WHERE action = 'routing.publish'"
        "   AND ts > now() - make_interval(hours => $1)"
        " ORDER BY ts DESC LIMIT 100",
        hours,
    )
    for r in pubs:
        out.append({"ts": r["ts"].isoformat(), "kind": "rule_publish",
                    "label": f"публикувано правило: {r['entity_id']}"})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return {"data": {"hours": hours, "events": out[:400]}}


def _fill_hour_buckets(counts: dict, hours: int) -> list:
    """Почасови кофи, запълнени с нули до hours+1 (текущият час е последната,
    непълна кофа). Споделен от stats/overview и dashboard (Т8) — консистентност
    по конструкция."""
    from datetime import datetime, timedelta, timezone

    now_h = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        {"hour": (now_h - timedelta(hours=i)).isoformat(),
         "count": counts.get((now_h - timedelta(hours=i)).isoformat(), 0)}
        for i in range(hours, -1, -1)
    ]


@router.get("/stats/overview")
async def stats_overview(
    request: Request, hours: int = 24, user: CurrentUser = Depends(require_viewer)
):
    pool = request.app.state.pool
    hours = min(max(hours, 1), 168)
    rows = await pool.fetch(
        "SELECT date_trunc('hour', ts) AS h, count(*) AS n FROM packets"
        " WHERE ts > now() - make_interval(hours => $1) GROUP BY 1 ORDER BY 1",
        hours,
    )
    counts = {r["h"].isoformat(): r["n"] for r in rows}
    buckets = _fill_hour_buckets(counts, hours)

    fam_rows = await pool.fetch(
        "SELECT topic, count(*) AS n FROM packets"
        " WHERE ts > now() - make_interval(hours => $1)"
        " GROUP BY topic ORDER BY n DESC LIMIT 200",
        hours,
    )
    fams: dict[str, int] = {}
    for r in fam_rows:
        fams[_family(r["topic"])] = fams.get(_family(r["topic"]), 0) + r["n"]
    families = sorted(
        [{"family": k, "count": v} for k, v in fams.items()], key=lambda x: -x["count"]
    )[:12]

    bat_rows = await pool.fetch(
        "SELECT topic, payload_text, payload_raw, ts FROM packets"
        " WHERE (payload_text LIKE '%battery%' OR decoder_id = 'meshtastic-protobuf')"
        " AND ts > now() - make_interval(hours => $1)"
        " ORDER BY ts DESC LIMIT 300",
        hours,
    )
    from ..ingest.mesh_decode import decode_envelope_protobuf, envelope_info, topic_parts

    batteries: dict[str, dict] = {}
    for r in bat_rows:
        try:
            doc = json.loads(r["payload_text"])
        except (json.JSONDecodeError, TypeError):
            doc = None
        battery = node = None
        if r["topic"].startswith("msh/"):
            info = envelope_info(r["payload_text"] or "")
            if info is None and r["payload_raw"]:
                # бинарен protobuf envelope (3b) — батерията идва от вътрешния decode
                info = decode_envelope_protobuf(
                    bytes(r["payload_raw"]),
                    getattr(getattr(request.app.state, "ingest", None), "psk_map", None))
            if info:
                battery = info["battery"]
                node = info["node_id"] or topic_parts(r["topic"])["node"]
        elif isinstance(doc, dict) and isinstance(doc.get("battery"), (int, float)):
            battery = doc["battery"]
            node = str(doc.get("node") or r["topic"].split("/")[-2])
        if battery is None or node is None:
            continue
        batteries.setdefault(
            node, {"node": node, "battery": battery, "ts": r["ts"].isoformat()}
        )

    rules = await pool.fetch(
        "SELECT r.name, r.enabled, s.matched, s.forwarded, s.errors, s.last_fired_at"
        " FROM routing_rules r LEFT JOIN routing_stats s ON s.rule_id = r.id"
        " ORDER BY r.priority, r.created_at"
    )
    ingest = getattr(request.app.state, "ingest", None)
    return {
        "data": {
            "buckets": buckets,
            "families": families,
            "batteries": sorted(batteries.values(), key=lambda b: b["battery"]),
            "mesh_deduped": getattr(ingest, "mesh_deduped", 0),
            "rules": [
                {
                    "name": r["name"],
                    "enabled": r["enabled"],
                    "matched": r["matched"] or 0,
                    "forwarded": r["forwarded"] or 0,
                    "errors": r["errors"] or 0,
                    "last_fired_at": r["last_fired_at"].isoformat() if r["last_fired_at"] else None,
                }
                for r in rules
            ],
        }
    }


# ---------- Т30: Фунията (Полезност) ---------------------------------------
# Ефир → Декодируеми → Хванати → Доставени → Deadletter: ЕДИН GET с бройки
# от packets + routing_executions; процентите ги смята UI-то (клик-до-trace).

@router.get("/stats/funnel")
async def stats_funnel(request: Request, hours: int = 24,
                       user: CurrentUser = Depends(require_viewer)):
    """Фуния на полезността за прозореца: колко от ефира се декодира,
    хваща от правилата, доставя и колко отива в мъртвите букви. Източници:
    packets (ефир/декод/доставени-с-origin/deadletter) + routing_executions
    (хванати). Нулите са ВИДИМИ — no-data е състояние, не грешка."""
    hours = min(max(hours, 1), 24 * 30)
    pool = request.app.state.pool
    async def one(q: str):
        return await pool.fetchval(
            q.replace("$W", f"now() - make_interval(hours => {int(hours)})"))
    air = await one(
        "SELECT count(*) FROM packets WHERE ts > $W")
    decoded = await one(
        "SELECT count(*) FROM packets"
        " WHERE ts > $W AND decode_status = 'decoded'")
    captured = await one(
        "SELECT count(*) FROM routing_executions"
        " WHERE ts > $W AND decision = 'match_forward'")
    delivered = await one(
        "SELECT count(*) FROM packets"
        " WHERE ts > $W AND origin LIKE 'routing:%'")
    dead = await one(
        "SELECT count(*) FROM packets"
        " WHERE ts > $W AND topic LIKE 'deadletter/%'")
    return {"data": {
        "hours": hours,
        "air": air or 0,
        "decoded": decoded or 0,
        "captured": captured or 0,
        "delivered": delivered or 0,
        "deadletter": dead or 0,
    }}


# ---------- Т36 срез 2: история на имената + pubkey групи -------------------

@router.get("/names/history")
async def names_history(request: Request, node: str,
                        user: CurrentUser = Depends(require_viewer)):
    """Кога възелът е сменял имена (NODEINFO наблюдения; миграция 017).
    Отвореният период (valid_to IS NULL) е текущото име от node_registry."""
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT long_name, short_name, valid_from, valid_to"
        " FROM node_names_history WHERE node_id = lower($1)"
        " ORDER BY valid_from DESC LIMIT 50", node)
    cur = await pool.fetchrow(
        "SELECT long_name, short_name FROM node_registry WHERE node_id = lower($1)", node)
    return {"data": {
        "node": node,
        "current": {"long_name": cur and cur["long_name"],
                    "short_name": cur and cur["short_name"]},
        "history": [
            {"long_name": r["long_name"], "short_name": r["short_name"],
             "valid_from": r["valid_from"].isoformat(),
             "valid_to": r["valid_to"].isoformat() if r["valid_to"] else None}
            for r in rows
        ],
    }}


@router.get("/names/pubkey-groups")
async def names_pubkey_groups(request: Request,
                              user: CurrentUser = Depends(require_viewer)):
    """Възли с ЕДНАКЪВ pubkey_fp — ре-флашнато устройство с нов node id
    носи същия ключ; групирането свързва старото и новото име/възел."""
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT pubkey_fp, array_agg(node_id ORDER BY node_id) AS nodes,"
        " array_agg(DISTINCT coalesce(long_name, short_name, node_id)) AS names"
        " FROM node_registry WHERE pubkey_fp IS NOT NULL"
        " GROUP BY pubkey_fp HAVING count(*) > 1 ORDER BY count(*) DESC LIMIT 100")
    return {"data": {
        "groups": [
            {"pubkey_fp": r["pubkey_fp"], "nodes": list(r["nodes"]),
             "names": list(r["names"])}
            for r in rows
        ]
    }}
