"""Routing Rules API (docs/09-routing-rules-plan.md §5)."""

import json
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..routing.engine import evaluate
from ..routing.model import RuleDefinition
from ..security import CurrentUser, audit, require_admin, require_operator, require_viewer

router = APIRouter(prefix="/v1/routing", tags=["routing"])


def _validate_http_destinations(defn: RuleDefinition) -> None:
    """SSRF вратичка като при мостовете/известията: http дестинации в правила
    сочат САМО навън (loopback/частни мрежи — не), за да не се превръща
    правилото в трамплин към вътрешни услуги."""
    from .bridges import validate_remote_host

    for d in defn.destinations:
        if d.type != "http":
            continue
        host = urlparse(d.url or "").hostname or ""
        if not host:
            raise HTTPException(422, detail=f"http дестинация без хост в url: {d.url!r}")
        validate_remote_host(host, allow_internal=False)


# Шаблоните са входна точка на „Създай правило" (план §D2) — предпопълнен wizard.
ROUTING_TEMPLATES: dict[str, dict] = {
    "low-battery-alert": {
        "title": "Ниска батерия → аларма",
        "description": "Телеметрия с батерия под 20% → тема alerts/battery/<node>, "
        "запазена (retain) за по-късно четене. Батерията се чете от декодирания "
        "Meshtastic envelope ($.battery); хваща и старите демо теми mesh/…/up.",
        "definition": {
            "name": "Ниска батерия → аларма",
            "priority": 50,
            "source": {"topic_filter": "#"},
            "conditions": {
                "topic": {"include": ["msh/#", "mesh/+/+/up"], "exclude": []},
                "payload": {
                    "mode": "all",
                    "terms": [{"path": "$.battery", "op": "lt", "value": 20}],
                },
            },
            "transform": {"topic_template": "alerts/battery/{payload.node}"},
            "destinations": [
                {
                    "type": "mqtt",
                    "target": "local",
                    "topic_template": "alerts/battery/{payload.node}",
                    "qos": 1,
                    "retain": True,
                }
            ],
        },
    },
    "http-post-forward": {
        "title": "POST към URL (n8n / Node-RED / ntfy)",
        "description": "Всяко съобщение от даден канал/тема се праща като HTTP "
        "POST към твой URL — вратата към n8n, Node-RED, ntfy push, собствени "
        "API-та. Замести url-а с реалния адрес (само външни хостове).",
        "definition": {
            "name": "Канал → HTTP",
            "priority": 150,
            "source": {"topic_filter": "msh/#"},
            "conditions": {"topic": {"include": ["msh/#"], "exclude": []}},
            "destinations": [
                {
                    "type": "http",
                    "target": "http",
                    "topic_template": "{topic}",
                    "qos": 0,
                    "retain": False,
                    "url": "https://example.com/your-endpoint",
                }
            ],
        },
    },
    "copy-zone-to-bridge": {
        "title": "Копирай зона към външен брокер",
        "description": "Всички telemetry съобщения → избран bridge (замести "
        "bridge:<uuid> с реален идентификатор от Bridges).",
        "definition": {
            "name": "Зона → външен брокер",
            "source": {"topic_filter": "mesh/+/+/up"},
            "conditions": {"topic": {"include": ["mesh/+/+/up"], "exclude": []}},
            "destinations": [
                {
                    "type": "mqtt",
                    "target": "bridge:REPLACE_ME",
                    "topic_template": "{topic}",
                    "qos": 1,
                }
            ],
        },
    },
    "exclude-private": {
        "title": "Изключи частните съобщения",
        "description": "Пуска всичко от mesh/ освен priv темите навътре в "
        "архивна тема (предпазен шаблон).",
        "definition": {
            "name": "Без частни съобщения",
            "source": {"topic_filter": "mesh/#"},
            "conditions": {
                "topic": {"include": ["mesh/#"], "exclude": ["mesh/+/+/priv"]}
            },
            "destinations": [
                {
                    "type": "mqtt",
                    "target": "local",
                    "topic_template": "archive/{topic}",
                    "qos": 0,
                }
            ],
        },
    },
    "archive-all": {
        "title": "Всичко към архив",
        "description": "Всички теми → локална архивна тема archive/<оригинална тема>.",
        "definition": {
            "name": "Всичко към архив",
            "source": {"topic_filter": "#"},
            "conditions": {"topic": {"include": ["#"], "exclude": ["archive/#"]}},
            "destinations": [
                {
                    "type": "mqtt",
                    "target": "local",
                    "topic_template": "archive/{topic}",
                    "qos": 0,
                }
            ],
        },
    },
    "channel-match-bridge": {
        "title": "Съвпадащи канали → мост (две мрежи)",
        "description": "Сценарият на собственика: устройство в мрежа A и устройство "
        "в мрежа B (различни честоти), каналите съвпадат — съобщенията от "
        "канала на A се препращат в същия канал на B. Замести netA/netB. "
        "Meshtastic↔MeshCore вариантът идва с адаптерите (Фаза M).",
        "definition": {
            "name": "Канал A ↔ канал B",
            "priority": 60,
            "source": {"topic_filter": "mesh/netA/#"},
            "conditions": {"topic": {"include": ["mesh/netA/#"], "exclude": []}},
            "transform": {"topic_template": "mesh/netB/{topic_suffix[2]}"},
            "destinations": [
                {
                    "type": "mqtt",
                    "target": "local",
                    "topic_template": "mesh/netB/{topic_suffix[2]}",
                    "qos": 1,
                }
            ],
        },
    },
    "channel-to-channel": {
        "title": "Канал → друг канал",
        "description": "Пренасочване на трафика от един канал към друг в същата "
        "мрежа (remap на канала, payload без промяна). Замести channelA/channelB.",
        "definition": {
            "name": "Канал → канал",
            "source": {"topic_filter": "mesh/+/channelA/#"},
            "conditions": {"topic": {"include": ["mesh/+/channelA/#"], "exclude": []}},
            "destinations": [
                {
                    "type": "mqtt",
                    "target": "local",
                    "topic_template": "mesh/{topic_tokens[1]}/channelB/{topic_suffix[3]}",
                    "qos": 1,
                }
            ],
        },
    },
    "channel-to-public-broker": {
        "title": "Канал → обществен брокер",
        "description": "Съобщенията от даден канал → публичен MQTT брокер чрез "
        "bridge (замести bridge:<uuid>; bridge-ът трябва да е активен). "
        "Изключено по подразбиране — включи съзнателно.",
        "definition": {
            "name": "Канал → обществен брокер",
            "source": {"topic_filter": "mesh/+/chat/#"},
            "conditions": {"topic": {"include": ["mesh/+/chat/#"], "exclude": []}},
            "destinations": [
                {
                    "type": "mqtt",
                    "target": "bridge:REPLACE_ME",
                    "topic_template": "{topic}",
                    "qos": 1,
                }
            ],
        },
    },
}


class CreateIn(BaseModel):
    definition: RuleDefinition | None = None
    template_id: str | None = None
    name: str | None = Field(default=None, min_length=2, max_length=64)
    description: str | None = None


class PatchIn(BaseModel):
    definition: RuleDefinition


class PublishIn(BaseModel):
    note: str | None = None


class RollbackIn(BaseModel):
    version: int = Field(ge=1)


class DryRunIn(BaseModel):
    definition: RuleDefinition | None = None
    rule_id: str | None = None
    topic: str = Field(min_length=1, max_length=256)
    payload: str = Field(default="", max_length=65536)


async def _load_rule(pool, rule_id: str) -> dict:
    r = await pool.fetchrow(
        "SELECT r.id, r.name, r.description, r.enabled, r.priority,"
        " r.execution_mode, r.definition, r.draft, r.current_version,"
        " s.matched, s.forwarded, s.errors, s.last_fired_at"
        " FROM routing_rules r LEFT JOIN routing_stats s ON s.rule_id = r.id"
        " WHERE r.id = $1",
        rule_id,
    )
    if not r:
        raise HTTPException(status_code=404, detail="not_found")
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "description": r["description"],
        "enabled": r["enabled"],
        "priority": r["priority"],
        "execution_mode": r["execution_mode"],
        "definition": json.loads(r["definition"]),
        "draft": json.loads(r["draft"]) if r["draft"] else None,
        "current_version": r["current_version"],
        "stats": {
            "matched": r["matched"] or 0,
            "forwarded": r["forwarded"] or 0,
            "errors": r["errors"] or 0,
            "last_fired_at": r["last_fired_at"].isoformat() if r["last_fired_at"] else None,
        },
    }


@router.get("/templates")
async def list_templates(request: Request, user: CurrentUser = Depends(require_viewer)):
    """Шаблоните се връщат като ПЪЛНИ дефиниции — през RuleDefinition, за да
    имат всички полета default-ите си (wizard-ът не бива да ги допълва)."""
    out = []
    for tid, tpl in ROUTING_TEMPLATES.items():
        defn = RuleDefinition(**{**tpl["definition"], "enabled": False})
        out.append(
            {
                "id": tid,
                "title": tpl["title"],
                "description": tpl["description"],
                "definition": json.loads(defn.model_dump_json()),
            }
        )
    return {"data": out}


@router.get("/samples")
async def samples(request: Request, user: CurrentUser = Depends(require_viewer)):
    """Последните реални съобщения с payload — wizard-ът от тях предлага
    тестови данни и paths за payload условията (автоматизация D3+)."""
    rows = await request.app.state.pool.fetch(
        "SELECT topic, payload_text, ts FROM packets"
        " WHERE payload_text IS NOT NULL AND ts > now() - interval '2 hours'"
        " ORDER BY ts DESC LIMIT 30"
    )
    return {
        "data": [
            {"topic": r["topic"], "payload": (r["payload_text"] or "")[:2048],
             "ts": r["ts"].isoformat()}
            for r in rows
        ]
    }


@router.get("/recent-topics")
async def recent_topics(request: Request, user: CurrentUser = Depends(require_viewer)):
    """Последните реални теми — за live подсказки в wizard-а (план §D3)."""
    rows = await request.app.state.pool.fetch(
        "SELECT topic, count(*) AS n, max(ts) AS last_at FROM packets"
        " WHERE ts > now() - interval '2 hours'"
        " GROUP BY topic ORDER BY last_at DESC LIMIT 50"
    )
    return {
        "data": [
            {"topic": r["topic"], "count": r["n"], "last_at": r["last_at"].isoformat()}
            for r in rows
        ]
    }


@router.get("")
async def list_rules(request: Request, user: CurrentUser = Depends(require_viewer)):
    rows = await request.app.state.pool.fetch(
        "SELECT r.id FROM routing_rules r ORDER BY r.priority, r.created_at"
    )
    out = []
    for r in rows:
        out.append(await _load_rule(request.app.state.pool, str(r["id"])))
    return {"data": out}


@router.post("", status_code=201)
async def create_rule(body: CreateIn, request: Request, user: CurrentUser = Depends(require_admin)):
    """Ново правило — винаги disabled; template_id е предпопълнен wizard."""
    pool = request.app.state.pool
    if body.template_id:
        tpl = ROUTING_TEMPLATES.get(body.template_id)
        if not tpl:
            raise HTTPException(status_code=404, detail=f"not_found: шаблон {body.template_id}")
        defn = tpl["definition"].copy()
        defn["enabled"] = False
        if body.name:
            defn["name"] = body.name
        desc = body.description or tpl["description"]
    elif body.definition:
        defn = body.definition.model_dump()
        defn["enabled"] = False  # safe by default (план §D7)
        desc = body.description or body.definition.description
    else:
        raise HTTPException(status_code=422, detail="трябва definition или template_id")
    rule = RuleDefinition(**defn)
    _validate_http_destinations(rule)
    if await pool.fetchval("SELECT 1 FROM routing_rules WHERE name=$1", rule.name):
        raise HTTPException(status_code=409, detail=f"conflict: име '{rule.name}' е заето")
    async with pool.acquire() as conn:
        async with conn.transaction():
            rid = await conn.fetchval(
                "INSERT INTO routing_rules (name, description, enabled, priority,"
                " execution_mode, definition, current_version, created_by)"
                " VALUES ($1,$2,false,$3,$4,$5::jsonb,1,$6) RETURNING id",
                rule.name,
                desc,
                rule.priority,
                rule.execution_mode,
                rule.model_dump_json(),
                user.username,
            )
            await conn.execute(
                "INSERT INTO routing_rule_versions (rule_id, version, definition, note, published_by)"
                " VALUES ($1, 1, $2::jsonb, 'създадено', $3)",
                rid,
                rule.model_dump_json(),
                user.username,
            )
    await audit(pool, user, "routing.create", "routing_rule", rule.name,
                {"from_template": body.template_id})
    await request.app.state.routing.reload()
    return {"data": await _load_rule(pool, str(rid))}


@router.post("/hold-back/flush")
async def hold_back_flush(request: Request, user: CurrentUser = Depends(require_operator)):
    """Т26: „Изпрати сега" — пуска всички задържани доставки веднага."""
    routing = request.app.state.routing
    held = list(routing.held_back)
    routing.held_back.clear()
    delivered = 0
    errors: list[str] = []
    for rule_id, out, topic, payload_doc in held:
        # _deliver връща (ok, err) — провалът НЕ брои за delivered
        ok, err = await routing._deliver(rule_id, out)
        if ok:
            delivered += 1
        elif err:
            errors.append(err)
    await audit(request.app.state.pool, user, "routing.hold_back_flush",
                "routing_rule", "hold-back",
                {"flushed": len(held), "delivered": delivered, "errors": len(errors)})
    return {"data": {"flushed": len(held), "delivered": delivered,
                     "errors": errors[:5]}}


@router.get("/hold-back")
async def hold_back_list(request: Request, user: CurrentUser = Depends(require_viewer)):
    routing = request.app.state.routing
    return {"data": {"held": len(routing.held_back), "total_ever": routing.hold_back_total}}


@router.get("/{rule_id}")
async def get_rule(rule_id: str, request: Request, user: CurrentUser = Depends(require_viewer)):
    return {"data": await _load_rule(request.app.state.pool, rule_id)}


@router.patch("/{rule_id}")
async def patch_rule(
    rule_id: str, body: PatchIn, request: Request, user: CurrentUser = Depends(require_admin)
):
    """Редакцията отива в draft; влиза в сила едва с publish (план §D4/D7)."""
    pool = request.app.state.pool
    current = await _load_rule(pool, rule_id)
    if body.definition.name != current["name"]:
        taken = await pool.fetchval(
            "SELECT 1 FROM routing_rules WHERE name=$1 AND id <> $2",
            body.definition.name, rule_id,
        )
        if taken:
            raise HTTPException(status_code=409, detail="conflict: име заето")
    _validate_http_destinations(body.definition)
    await pool.execute(
        "UPDATE routing_rules SET draft=$1::jsonb, updated_at=now() WHERE id=$2",
        body.definition.model_dump_json(),
        rule_id,
    )
    await audit(pool, user, "routing.edit_draft", "routing_rule", body.definition.name, {})
    return {"data": await _load_rule(pool, rule_id)}


@router.post("/{rule_id}/publish")
async def publish_rule(
    rule_id: str, body: PublishIn | None, request: Request, user: CurrentUser = Depends(require_admin)
):
    pool = request.app.state.pool
    # Т23: АТОМАРЕН publish — SELECT FOR UPDATE сериализира конкурентните
    # publishes (никой пакет не се оценява срещу полу-публикувано правило;
    # версията се смята В транзакцията, вторият publish вижда новата)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, definition, draft, current_version FROM routing_rules"
                " WHERE id = $1 FOR UPDATE", rule_id)
            if row is None:
                raise HTTPException(status_code=404, detail="not_found")
            source = row["draft"] or row["definition"]
            rule = RuleDefinition(**json.loads(source) if isinstance(source, str) else source)
            version = (row["current_version"] or 0) + 1
            await conn.execute(
                "UPDATE routing_rules SET definition=$1::jsonb, draft=NULL,"
                " priority=$2, execution_mode=$3, current_version=$4, updated_at=now()"
                " WHERE id=$5",
                rule.model_dump_json(),
                rule.priority,
                rule.execution_mode,
                version,
                rule_id,
            )
            await conn.execute(
                "INSERT INTO routing_rule_versions (rule_id, version, definition, note, published_by)"
                " VALUES ($1,$2,$3::jsonb,$4,$5)",
                rule_id,
                version,
                rule.model_dump_json(),
                (body.note if body else None) or "публикувано",
                user.username,
            )
    await audit(pool, user, "routing.publish", "routing_rule", rule.name, {"version": version})
    await request.app.state.routing.reload()
    return {"data": {**await _load_rule(pool, rule_id), "published_version": version}}


@router.post("/{rule_id}/rollback")
async def rollback_rule(
    rule_id: str, body: RollbackIn, request: Request, user: CurrentUser = Depends(require_admin)
):
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "SELECT definition FROM routing_rule_versions WHERE rule_id=$1 AND version=$2",
        rule_id,
        body.version,
    )
    if not row:
        raise HTTPException(status_code=404, detail="not_found: версията не съществува")
    rule = RuleDefinition(**json.loads(row["definition"]))
    # Т23 П3: версията и редът се заключват В транзакцията (като publish) —
    # конкурентни rollback+publish не генерират една и съща версия
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur = await conn.fetchrow(
                "SELECT current_version FROM routing_rules WHERE id = $1 FOR UPDATE",
                rule_id)
            if cur is None:
                raise HTTPException(status_code=404, detail="not_found")
            version = (cur["current_version"] or 0) + 1
            await conn.execute(
                "UPDATE routing_rules SET definition=$1::jsonb, draft=NULL,"
                " priority=$2, execution_mode=$3, current_version=$4, updated_at=now()"
                " WHERE id=$5",
                rule.model_dump_json(),
                rule.priority,
                rule.execution_mode,
                version,
                rule_id,
            )
            await conn.execute(
                "INSERT INTO routing_rule_versions (rule_id, version, definition, note, published_by)"
                " VALUES ($1,$2,$3::jsonb,$4,$5)",
                rule_id,
                version,
                rule.model_dump_json(),
                f"rollback към v{body.version}",
                user.username,
            )
    await audit(pool, user, "routing.rollback", "routing_rule", rule.name,
                {"to_version": body.version, "new_version": version})
    await request.app.state.routing.reload()
    return {"data": {**await _load_rule(pool, rule_id), "published_version": version}}


@router.post("/{rule_id}/enable")
async def enable_rule(
    rule_id: str, request: Request, user: CurrentUser = Depends(require_operator)
):
    pool = request.app.state.pool
    name = await pool.fetchval(
        "UPDATE routing_rules SET enabled=true, updated_at=now() WHERE id=$1 RETURNING name",
        rule_id,
    )
    if not name:
        raise HTTPException(status_code=404, detail="not_found")
    await audit(pool, user, "routing.enable", "routing_rule", name)
    await request.app.state.routing.reload()
    return {"data": await _load_rule(pool, rule_id)}


@router.post("/{rule_id}/disable")
async def disable_rule(
    rule_id: str, request: Request, user: CurrentUser = Depends(require_operator)
):
    pool = request.app.state.pool
    name = await pool.fetchval(
        "UPDATE routing_rules SET enabled=false, updated_at=now() WHERE id=$1 RETURNING name",
        rule_id,
    )
    if not name:
        raise HTTPException(status_code=404, detail="not_found")
    await audit(pool, user, "routing.disable", "routing_rule", name)
    await request.app.state.routing.reload()
    return {"data": await _load_rule(pool, rule_id)}


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: str, request: Request, user: CurrentUser = Depends(require_admin)
):
    pool = request.app.state.pool
    name = await pool.fetchval("DELETE FROM routing_rules WHERE id=$1 RETURNING name", rule_id)
    if not name:
        raise HTTPException(status_code=404, detail="not_found")
    await audit(pool, user, "routing.delete", "routing_rule", name)
    await request.app.state.routing.reload()
    return {"data": {"ok": True}}


@router.get("/{rule_id}/versions")
async def rule_versions(
    rule_id: str, request: Request, user: CurrentUser = Depends(require_viewer)
):
    rows = await request.app.state.pool.fetch(
        "SELECT version, definition, note, published_by, published_at"
        " FROM routing_rule_versions WHERE rule_id=$1 ORDER BY version",
        rule_id,
    )
    return {
        "data": [
            {
                "version": r["version"],
                "definition": json.loads(r["definition"]),
                "note": r["note"],
                "published_by": r["published_by"],
                "published_at": r["published_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/{rule_id}/executions")
async def rule_executions(
    rule_id: str,
    request: Request,
    decision: str | None = None,
    limit: int = 50,
    user: CurrentUser = Depends(require_viewer),
):
    limit = min(limit, 200)
    pool = request.app.state.pool
    if decision:
        rows = await pool.fetch(
            "SELECT ts, input_topic, decision, steps, error, duration_ms"
            " FROM routing_executions WHERE rule_id=$1 AND decision=$2"
            " ORDER BY ts DESC LIMIT $3",
            rule_id, decision, limit,
        )
    else:
        rows = await pool.fetch(
            "SELECT ts, input_topic, decision, steps, error, duration_ms"
            " FROM routing_executions WHERE rule_id=$1 ORDER BY ts DESC LIMIT $2",
            rule_id, limit,
        )
    return {
        "data": [
            {
                "ts": r["ts"].isoformat(),
                "input_topic": r["input_topic"],
                "decision": r["decision"],
                "steps": json.loads(r["steps"]) if r["steps"] else [],
                "error": r["error"],
                "duration_ms": r["duration_ms"],
            }
            for r in rows
        ]
    }


@router.post("/deadletter/resend")
async def resend_dead_letter(
    body: dict, request: Request, user: CurrentUser = Depends(require_admin)
):
    """R2: повторно изпращане на мъртва буква — по packet_id на съобщение от
    deadletter/<правило>. Оригиналният payload отива към оригиналната цел."""
    import base64

    pool = request.app.state.pool
    packet_id = str(body.get("packet_id") or "")
    row = await pool.fetchrow(
        "SELECT topic, payload_text FROM packets WHERE id = $1 AND topic LIKE 'deadletter/%'",
        packet_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="not_found: няма такава мъртва буква")
    try:
        doc = json.loads(row["payload_text"] or "")
        payload = base64.b64decode(doc["payload_b64"])
        target, topic = doc["target"], doc["topic"]
        qos = int(doc.get("qos", 0))
        retain = bool(doc.get("retain", False))
    except Exception:
        raise HTTPException(status_code=422, detail="не може да се разпакетира мъртвата буква")
    routing = request.app.state.routing
    if target == "local":
        await request.app.state.ingest.publish_local(
            topic, payload, "routing:resend", qos, retain
        )
        sent = target
    elif str(target).startswith("bridge:"):
        ok, err = routing.bridge.enqueue(
            str(target)[7:], topic, payload, qos, retain
        )
        if not ok:
            raise HTTPException(status_code=502, detail=f"bridge не приема: {err}")
        sent = target
    else:
        raise HTTPException(status_code=422, detail=f"непозната цел {target}")
    await audit(pool, user, "routing.deadletter_resend", "packet", packet_id,
                {"target": target, "topic": topic})
    return {"data": {"resent": packet_id, "target": sent, "topic": topic}}


@router.post("/validate")
async def validate_definition(body: DryRunIn, request: Request,
                              user: CurrentUser = Depends(require_operator)):
    """Т21: валидация с човешки грешки ПРЕДИ запис/публикуване:
    • празни дестинации / липсващ topic_template
    • дестинация към несъществуващ мост
    • цикличен include: шаблонът на изхода пасва на собствения include
    Върни {errors: [блокери], warnings: [предупреждения]}."""
    pool = request.app.state.pool
    if not body.definition:
        raise HTTPException(status_code=422, detail="трябва definition")
    defn = body.definition
    errors: list[str] = []
    warnings: list[str] = []

    if not defn.destinations:
        errors.append("Няма нито една дестинация — правилото няма къде да пише.")
    for d in defn.destinations:
        if not d.topic_template or not d.topic_template.strip():
            errors.append("Дестинация без topic_template — към коя тема да пише?")
        if d.target.startswith("bridge:"):
            bid = d.target[7:]
            # шаблоните носят bridge:REPLACE_ME — не-UUID не бива да стига
            # до asyncpg (DataError -> 500); човешката грешка е по-полезна
            import uuid as _uuid
            try:
                _uuid.UUID(bid)
            except (ValueError, AttributeError):
                errors.append(f"Дестинацията сочи към несъществуващ мост {bid}.")
                continue
            exists = await pool.fetchval(
                "SELECT 1 FROM bridge_configs WHERE id = $1", bid)
            if not exists:
                errors.append(f"Дестинацията сочи към несъществуващ мост {bid}.")
    if not defn.conditions.topic.include and defn.source.topic_filter == "#":
        warnings.append("Няма include условия и филтърът е # — правилото хваща ВСИЧКО; прецизирай темите.")
    # цикъл: изходната тема пасва на собствения include
    outputs_topics = [d.topic_template for d in defn.destinations if d.topic_template]
    for pat in defn.conditions.topic.include:
        for ot in outputs_topics:
            from ..bridge.rules import mqtt_match
            # шаблоните на изхода имат {placeholder} — заместваме с + за мачване
            probe = re.sub(r"\{[^}]+\}", "+", ot)
            if mqtt_match(pat, probe) or mqtt_match(probe, pat):
                warnings.append(
                    f"Цикъл: изходът „{ot}“ пасва на собствения include „{pat}“ —"
                    " пакетът ще се върне към същото правило (защитено от origin маркера, но провери дали е нарочно).")
    return {"data": {"errors": errors, "warnings": warnings}}


@router.post("/dry-run")
async def dry_run(body: DryRunIn, request: Request, user: CurrentUser = Depends(require_operator)):
    """Симулация без публикуване: пълен trace на всяка стъпка (план §D5)."""
    pool = request.app.state.pool
    if body.rule_id:
        row = await pool.fetchrow(
            "SELECT id, definition FROM routing_rules WHERE id=$1", body.rule_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="not_found")
        defn = RuleDefinition(**json.loads(row["definition"]))
        db_id = {defn.name: str(row["id"])}
    elif body.definition:
        defn = body.definition
        db_id = {}
    else:
        raise HTTPException(status_code=422, detail="трябва definition или rule_id")
    defn.enabled = True  # симулираме-active

    try:
        doc = json.loads(body.payload) if body.payload.strip() else None
    except json.JSONDecodeError:
        doc = body.payload  # текстов payload — условия по него не могат да минат
    traces = evaluate([defn], body.topic, body.payload.encode(), doc, "local", db_id)
    out = []
    for t in traces:
        out.append(
            {
                "rule_id": t.rule_id,
                "rule_name": t.rule_name,
                "decision": t.decision,
                "input_topic": t.input_topic,
                "steps": t.steps,
                "error": t.error,
                "outputs": [
                    {
                        "target": o.target,
                        "topic": o.topic,
                        "qos": o.qos,
                        "retain": o.retain,
                        "payload_preview": o.payload[:500].decode("utf-8", "replace"),
                    }
                    for o in t.outputs
                ],
                "preview": t.preview,
            }
        )
    return {"data": out}
