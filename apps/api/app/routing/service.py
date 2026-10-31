"""Routing service: зарежда правилата, доставя изходите до локалния брокер
или до bridge, пише журнал (routing_executions) и броячи (routing_stats).

Доставката почита error_policy на правилото (R2): retry с backoff при
провал, halt прескача следващите дестинации, а при изчерпани retry-та
съобщението отива в dead-letter тема deadletter/<правило> (retain) —
откъдето може да се изпрати повторно (POST /v1/routing/deadletter/resend)."""

import asyncio
import base64
import json
from typing import Any
import logging
import time

import asyncpg
import httpx

from ..bridge.engine import BridgeEngine
from .engine import Output, Trace, evaluate
from .model import ErrorPolicy, RuleDefinition

log = logging.getLogger("meshgate.routing")

EXEC_KEEP_PER_RULE = 200
DEAD_LETTER_PREFIX = "deadletter/"
MAX_BACKOFF_S = 60.0
HTTP_TIMEOUT_S = 10.0
# backpressure (R2): най-много толкова едновременни доставки — бавен HTTP
# endpoint не може да задръсти ingestion-а; при изчерпани слотове доставката
# се отказва честно (дедуп/рetry/мъртва буква по политиката на правилото)
DELIVERY_CONCURRENCY = 16
DELIVERY_SLOT_WAIT_S = 1.0
PRIORITY_SLOT_WAIT_S = DELIVERY_SLOT_WAIT_S * 6


def classify_priority(node_priority: str | None, payload_doc: Any) -> str:
    """Т25: клас на пакета — приоритетът на източника; 'auto' се извежда
    от съдържанието (severity=critical → urgent), иначе normal."""
    p = node_priority or "normal"
    if p != "auto":
        return p
    sev = None
    if isinstance(payload_doc, dict):
        sev = payload_doc.get("severity")
        if sev is None and isinstance(payload_doc.get("decoded"), dict):
            sev = payload_doc["decoded"].get("severity")
    return "urgent" if sev == "critical" else "normal"


def should_hold_back(prio: str, node: str | None, hold_map: dict[str, bool]) -> bool:
    """Т26: задръж ли се доставка — само normal на възел с hold_back
    (urgent/critical изминават през приоритетната лента винаги)."""
    return prio == "normal" and bool(node) and bool(hold_map.get(node.lower()))


class RoutingEngine:
    def __init__(self, pool: asyncpg.Pool, bridge: BridgeEngine):
        self.pool = pool
        self.bridge = bridge
        self.ingest = None  # свързва се в main.py (ingest има клиента към брокера)
        self.rules: list[RuleDefinition] = []
        self._db_ids: dict[str, str] = {}  # име на правило -> uuid (за trace)
        # HTTP дестинации (R2): POST с retry/dead-letter като mqtt доставки
        self.http = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
        self._slots = asyncio.Semaphore(DELIVERY_CONCURRENCY)
        # Т25: приоритетна лента — urgent/critical минават през отделни 4
        # слота с по-дълго изчакване, за да изпреварват при backpressure
        self._priority_slots = asyncio.Semaphore(4)
        self._node_priority: dict[str, str] = {}
        self._node_hold_back: dict[str, bool] = {}
        self.backpressured = 0  # брой отказани доставки от претоварване
        # Т26: hold-back — задържани normal доставки (изчакват SNR прозорец);
        # urgent/critical НИКОГА не се задържат
        self.held_back: list[tuple[str, "Output", str, Any]] = []
        self.hold_back_total = 0

    async def stop(self) -> None:
        await self.http.aclose()

    async def load(self) -> None:
        prio_rows = await self.pool.fetch(
            "SELECT external_id, routing_priority FROM devices"
            " WHERE routing_priority <> 'normal'")
        self._node_priority = {
            r["external_id"].lower(): r["routing_priority"] for r in prio_rows
        }
        hb_rows = await self.pool.fetch(
            "SELECT external_id FROM devices WHERE hold_back = true")
        self._node_hold_back = {r["external_id"].lower(): True for r in hb_rows}
        rows = await self.pool.fetch(
            "SELECT id, definition FROM routing_rules WHERE enabled = true"
        )
        rules: list[RuleDefinition] = []
        ids: dict[str, str] = {}
        for r in rows:
            try:
                d = RuleDefinition(**json.loads(r["definition"]))
                # колоната enabled е единствената истина — вграденото поле в
                # definition е само начално състояние от wizard-а
                d.enabled = True
                rules.append(d)
                ids[d.name] = str(r["id"])
            except Exception:
                log.exception("routing: невалидно правило %s — пропускаме го", r["id"])
        self.rules = rules
        self._db_ids = ids
        await self._prune_executions()
        log.info("routing: заредени %d активни правила", len(self.rules))

    async def reload(self) -> None:
        await self.load()

    # --- входна точка от ingestion ---

    async def handle_local(
        self, topic: str, payload: bytes, payload_doc, origin: str
    ) -> None:
        if not self.rules:
            return
        started = time.monotonic()
        traces = evaluate(
            self.rules, topic, payload, payload_doc, origin, self._db_ids
        )
        for t in traces:
            duration_ms = int((time.monotonic() - started) * 1000)
            delivered = failed = 0
            ep: ErrorPolicy = t.error_policy or ErrorPolicy()
            if t.decision == "match_forward":
                # Т25: клас на пакета — приоритетът на ИЗТОЧНИКА (auto → по
                # severity от payload-а); класът влиза в trace (audit)
                node = next((tok for tok in t.input_topic.split('/')
                             if tok.startswith('!')), None)
                prio = classify_priority(
                    self._node_priority.get(node.lower()) if node else None,
                    payload_doc)
                if prio != "normal":
                    t.steps.append({"step": f"клас: {prio} (приоритетна лента)"})
                # Т26: hold-back — нормалните доставки на възел с hold_back
                # се задържат (urgent/critical минават винаги). БЕЗ
                # traces.append тук — append вътре в for t in traces: го
                # посещава наново → безкраен цикъл (П3: 6520 журнальни реда
                # от ЕДИН пакет); continue + _record свършат работата.
                if should_hold_back(prio, node, self._node_hold_back):
                    t.steps.append({"step": f"hold-back: {len(t.outputs)} доставки задържани (изчакват прозорец/flush)"})
                    for out in t.outputs:
                        self.held_back.append((t.rule_id, out, t.input_topic, payload_doc))
                    self.hold_back_total += len(t.outputs)
                    await self._record(t, duration_ms, 0, 0)
                    continue
                for out in t.outputs:
                    # Т22: политиката на КЛОНА има приоритет (None → правилото)
                    ep_branch = out.error_policy or ep
                    ok, err, attempts = await self._deliver_with_retry(ep_branch, t, out, prio)
                    if ok:
                        delivered += 1
                        step = f"доставено до {out.target}"
                        if attempts > 1:
                            step += f" (след {attempts} опита)"
                        t.steps.append({"step": step})
                    else:
                        failed += 1
                        t.steps.append(
                            {"step": f"грешка при {out.target} след {attempts} опита: {err}"}
                        )
                        if ep_branch.dead_letter:
                            dl_topic, dl_msg = self._dead_letter(t, out, err)
                            ok_dl, err_dl = await self._deliver(
                                t.rule_id,
                                Output(dest_id=None, type="mqtt", target="local",
                                       topic=dl_topic, qos=1, retain=True,
                                       payload=dl_msg),
                            )
                            t.steps.append({
                                "step": (f"dead-letter → {dl_topic}" if ok_dl
                                         else f"dead-letter пропадна: {err_dl}"),
                            })
                        if ep_branch.on_destination_failure == "halt":
                            t.steps.append({
                                "step": "halt: следващите дестинации се прескачат",
                            })
                            break
            await self._record(t, duration_ms, delivered, failed)

    async def _deliver_with_retry(
        self, ep: ErrorPolicy, t: Trace, out: Output,
        priority: str = "normal",
    ) -> tuple[bool, str | None, int]:
        """1 + retry.max опита с пауза backoff_ms между тях. Изпълнява се под
        backpressure слот — бави доставки не задръстват ingestion-а.
        Т25: urgent/criticал минават през приоритетната лента (4 слота,
        6× по-дълго изчакване) — изпреварват при натоварване."""
        prio_acquired = False
        try:
            if priority in ("urgent", "critical"):
                async with asyncio.timeout(PRIORITY_SLOT_WAIT_S):
                    await self._priority_slots.acquire()
                prio_acquired = True
            async with asyncio.timeout(DELIVERY_SLOT_WAIT_S):
                await self._slots.acquire()
        except (TimeoutError, asyncio.TimeoutError):
            self.backpressured += 1
            # Т25 П3: взетият приоритетен слот СЕ ВРЪЩА — иначе всеки
            # timeout по главния слот убива трайно един от 4-те
            if prio_acquired:
                self._priority_slots.release()
                prio_acquired = False
            return False, (
                f"backpressure: {DELIVERY_CONCURRENCY} доставки вече текат —"
                " опитът се отказа (мъртва буква по политиката)"
            ), 0
        try:
            attempts = 1 + max(0, ep.retry.max)
            err: str | None = None
            for attempt in range(1, attempts + 1):
                ok, err = await self._deliver(t.rule_id, out)
                if ok:
                    return True, None, attempt
                if attempt < attempts:
                    await asyncio.sleep(
                        min(ep.retry.backoff_ms / 1000.0, MAX_BACKOFF_S)
                    )
            return False, err, attempts
        finally:
            self._slots.release()
            if prio_acquired:
                self._priority_slots.release()

    @staticmethod
    def _dead_letter(t: Trace, out: Output, err: str | None) -> tuple[str, bytes]:
        """Плик за мъртва буква: метаданни + оригиналния payload (base64),
        публикуван на deadletter/<правило> (retain) — за преглед и повторно
        изпращане. Origin marker-ът на publish пречи на цикъл."""
        doc = {
            "rule": t.rule_name,
            "input_topic": t.input_topic,
            "target": out.target,
            "topic": out.topic,
            "qos": out.qos,
            "retain": out.retain,
            "error": (err or "")[:300],
            "payload_b64": base64.b64encode(out.payload).decode("ascii"),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return (
            f"{DEAD_LETTER_PREFIX}{t.rule_name}",
            json.dumps(doc, ensure_ascii=False).encode("utf-8"),
        )

    async def _deliver(self, rule_id: str, out) -> tuple[bool, str | None]:
        origin_marker = f"routing:{rule_id}" if rule_id else "routing:unknown"
        try:
            if out.type == "http":
                # R2: HTTP дестинация — тялото е трансформираният payload;
                # JSON разпознат → application/json, иначе text/plain (ntfy)
                try:
                    json.loads(out.payload)
                    ctype = "application/json"
                except (ValueError, UnicodeDecodeError):
                    ctype = "text/plain"
                r = await self.http.post(
                    out.target, content=out.payload,
                    headers={"Content-Type": ctype,
                             "User-Agent": "MeshGate/0.1"},
                )
                r.raise_for_status()
                return True, None
            if out.target == "local":
                if self.ingest is None:
                    return False, "локалният издател не е наличен"
                await self.ingest.publish_local(
                    out.topic, out.payload, origin_marker, out.qos, out.retain
                )
                return True, None
            if out.target.startswith("bridge:"):
                bid = out.target[len("bridge:"):]
                ok, err = self.bridge.enqueue(bid, out.topic, out.payload, out.qos, out.retain)
                if not ok:
                    return False, err or f"bridge {bid} не е активен"
                return True, None
            return False, f"непозната дестинация: {out.target}"
        except Exception as exc:  # доставката никога не бива да руши ingestion
            return False, str(exc)

    async def _record(self, t: Trace, duration_ms: int, delivered: int, failed: int) -> None:
        """Журнал + броячи. Частично провалена дестинация (errorPolicy=continue)
        не сменя решението — грешката личи в стъпките и в брояча errors."""
        if not t.rule_id:
            return
        error = t.error
        decision = t.decision
        if decision == "match_forward" and failed and not delivered:
            decision = "error"
            error = error or "всички дестинации се провалиха"
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "INSERT INTO routing_executions (rule_id, input_topic,"
                        " decision, steps, error, duration_ms)"
                        " VALUES ($1,$2,$3,$4::jsonb,$5,$6)",
                        t.rule_id,
                        t.input_topic,
                        decision,
                        json.dumps(t.steps, ensure_ascii=False),
                        error,
                        duration_ms,
                    )
                    if decision == "match_forward":
                        await conn.execute(
                            "INSERT INTO routing_stats (rule_id, matched, forwarded,"
                            " last_fired_at) VALUES ($1, 1, $2, now())"
                            " ON CONFLICT (rule_id) DO UPDATE SET"
                            " matched = routing_stats.matched + 1,"
                            " forwarded = routing_stats.forwarded + $2,"
                            " errors = routing_stats.errors + $3,"
                            " last_fired_at = now()",
                            t.rule_id,
                            delivered,
                            failed,
                        )
                    elif decision == "error":
                        await conn.execute(
                            "INSERT INTO routing_stats (rule_id, errors)"
                            " VALUES ($1, $2)"
                            " ON CONFLICT (rule_id) DO UPDATE SET"
                            " errors = routing_stats.errors + $2",
                            t.rule_id,
                            1 + failed,
                        )
        except Exception:
            log.exception("routing_executions: записът пропадна")

    async def _prune_executions(self) -> None:
        """Журналът пази последните EXEC_KEEP_PER_RULE записи на правило."""
        await self.pool.execute(
            "DELETE FROM routing_executions e WHERE e.id IN ("
            "  SELECT id FROM ("
            "    SELECT id, row_number() OVER (PARTITION BY rule_id ORDER BY ts DESC)"
            "    AS rn FROM routing_executions"
            "  ) ranked WHERE ranked.rn > $1"
            ")",
            EXEC_KEEP_PER_RULE,
        )
