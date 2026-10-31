"""Deterministic routing engine: оценява правилата срещу едно съобщение и
връща пълен trace. Без I/O — публикуването е в service.py."""

from dataclasses import dataclass, field
from typing import Any

from ..bridge.rules import mqtt_match
from .match import payload_matches, topic_matches
from .model import ErrorPolicy, RuleDefinition
from .transform import TransformError, apply_transform, render_template


@dataclass
class Output:
    dest_id: str | None
    type: str
    target: str
    topic: str
    qos: int
    retain: bool
    payload: bytes
    # Т22: политиката на КЛОНА (разклонението) — None → важи правилото
    error_policy: "ErrorPolicy | None" = None


@dataclass
class Trace:
    rule_id: str
    rule_name: str
    decision: str  # match_forward | no_match | skipped_disabled | error
    input_topic: str = ""
    steps: list[dict] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    error: str | None = None
    # Т21: трансформацията преди/после (за Live preview в wizard стъпка 5)
    preview: dict | None = None
    # политиката за доставки (retry/halt/dead-letter) — носи се с трейса,
    # за да я приложи service.py без повторно търсене на правилото
    error_policy: ErrorPolicy | None = None


def evaluate(
    rules: list[RuleDefinition],
    topic: str,
    payload: bytes,
    payload_doc: Any,
    origin: str = "local",
    db_id: dict[str, str] | None = None,
) -> list[Trace]:
    """Оценява всички правила (по приоритет) срещу съобщението.

    execution_mode: правило в режим first_match, което е match-нало, спира
    оценката (останалите правила не се гледат); all_match продължава.
    Произход: 'local' е локално публикувано; 'bridge:<id>' е донесено от
    входящ мост — обработва се, НИТО една дестинация не може да върне
    съобщението към същия този мост (защита срещу цикъл). Други маркери
    (напр. routing:*) не се обработват изобщо."""
    if origin != "local" and not origin.startswith("bridge:"):
        return []
    db_id = db_id or {}
    traces: list[Trace] = []

    for rule in sorted(rules, key=lambda r: r.priority):
        t = Trace(
            rule_id=db_id.get(rule.name, ""),
            rule_name=rule.name,
            decision="no_match",
            input_topic=topic,
            steps=[],
            error_policy=rule.error_policy,
        )

        def step(msg: str) -> None:
            t.steps.append({"step": msg})

        if not rule.enabled:
            step("правилото е изключено")
            t.decision = "skipped_disabled"
            traces.append(t)
            continue
        if not mqtt_match(rule.source.topic_filter, topic):
            step(f"source филтър {rule.source.topic_filter} не пасва")
            traces.append(t)
            continue

        ok, why = topic_matches(rule.conditions.topic, topic)
        step(f"topic условия → {'пасва' if ok else 'не пасва'}: {why}")
        if not ok:
            traces.append(t)
            continue

        ok, reasons = payload_matches(rule.conditions.payload, payload_doc)
        for r in reasons:
            step(f"payload: {r}")
        if not ok:
            traces.append(t)
            continue

        try:
            new_topic, new_doc, out_bytes, tsteps = apply_transform(
                rule.transform, topic, payload_doc, payload
            )
        except TransformError as exc:
            t.error = f"transform: {exc}"
            step(t.error)
            t.decision = "error"
            traces.append(t)
            continue
        for s in tsteps:
            step(s)
        # Т21: преди/после за Live preview (темата и payload-ът)
        t.preview = {
            "topic_before": topic,
            "topic_after": new_topic,
            "payload_before": (payload_doc if isinstance(payload_doc, (dict, list))
                               else str(payload_doc)) if payload_doc is not None else None,
            "payload_after": (new_doc if isinstance(new_doc, (dict, list))
                              else str(new_doc)) if new_doc is not None else None,
            "changed": new_topic != topic or out_bytes != payload,
        }

        for dest in rule.destinations:
            # цикъл-защита: донесено от мост X не се връща към мост X
            if origin.startswith("bridge:") and dest.target == origin:
                step(f"дестинация {dest.target} пресечена: същият мост (цикъл)")
                continue
            if dest.type == "http":
                # R2: HTTP POST дестинация — payload-ът отива като тяло
                # (JSON → application/json, иначе text/plain); url-ът е в target
                if not (dest.url or "").startswith(("http://", "https://")):
                    t.error = f"http дестинация без валиден url: {dest.url!r}"
                    step(t.error)
                    t.decision = "error"
                    continue
                t.outputs.append(
                    Output(
                        dest_id=dest.id,
                        type="http",
                        target=dest.url,
                        topic=new_topic,
                        qos=0,
                        retain=False,
                        payload=out_bytes,
                        error_policy=dest.error_policy,
                    )
                )
                step(f"HTTP дестинация → {dest.url}")
                continue
            try:
                dest_topic = render_template(dest.topic_template, new_topic, new_doc)
            except TransformError as exc:
                t.error = f"дестинация {dest.target}: {exc}"
                step(t.error)
                t.decision = "error"
                continue
            t.outputs.append(
                Output(
                    dest_id=dest.id,
                    type=dest.type,
                    target=dest.target,
                    topic=dest_topic,
                    qos=dest.qos,
                    retain=dest.retain,
                    payload=out_bytes,
                    error_policy=dest.error_policy,  # Т22: политиката на КЛОНА
                )
            )
            step(f"дестинация {dest.target} → {dest_topic} (qos {dest.qos})")

        # грешка в дестинация (template/url) не се презаписва от успеха —
        # решението вече е "error" от цикъла горе
        if t.decision not in ("error",):
            t.decision = "match_forward"
        traces.append(t)
        if rule.execution_mode == "first_match":
            break
    return traces
