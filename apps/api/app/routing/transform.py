"""Трансформация на съобщение: topic template, set/remove полета, envelope."""

import json
import re
from typing import Any

from .model import TransformSpec

# {topic}, {topic_suffix[2]}, {topic_tokens[0]}, {payload.telemetry.battery}
_PLACEHOLDER_RE = re.compile(
    r"\{topic\}|\{topic_suffix\[\d+\]\}|\{topic_tokens\[\d+\]\}"
    r"|\{payload\.[A-Za-z0-9_.\[\]]+\}"
)

MAX_OUTPUT_BYTES = 50 * 1024
MAX_INPUT_BYTES = 32 * 1024


class TransformError(ValueError):
    pass


def render_template(template: str, topic: str, doc: Any) -> str:
    """Замества placeholder-ите; непознат/неразрешим → TransformError."""
    tokens = topic.split("/")

    def repl(m: re.Match) -> str:
        key = m.group(0)
        if key == "{topic}":
            return topic
        if key.startswith("{topic_suffix["):
            idx = int(key[len("{topic_suffix["):-2])
            if idx >= len(tokens):
                raise TransformError(
                    f"{key}: темата '{topic}' няма толкова токени"
                )
            return "/".join(tokens[idx:])
        if key.startswith("{topic_tokens["):
            idx = int(key[len("{topic_tokens["):-2])
            if idx >= len(tokens):
                raise TransformError(
                    f"{key}: темата '{topic}' няма толкова токени"
                )
            return tokens[idx]
        # {payload.<path>}
        from .match import get_path

        inner = key[1:-1]
        found, val = get_path(doc, "$" + inner[len("payload"):])
        if not found or val is None:
            raise TransformError(f"{key}: липсва в payload")
        if isinstance(val, (dict, list)):
            raise TransformError(f"{key}: обект/масив не е валидна тема")
        return str(val)

    return _PLACEHOLDER_RE.sub(repl, template)


def _split_path(path: str) -> list[str]:
    parts = [p for p in path.split(".") if p]
    if not parts or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p) for p in parts):
        raise TransformError(f"невалидно име на поле: {path!r}")
    return parts


def _set_field(doc: dict, path: str, value: Any) -> None:
    parts = _split_path(path)
    cur = doc
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _remove_field(doc: dict, path: str) -> None:
    parts = _split_path(path)
    cur: Any = doc
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return
        cur = cur[p]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def apply_transform(
    spec: TransformSpec, topic: str, payload_doc: Any, payload_bytes: bytes
) -> tuple[str, Any, bytes, list[str]]:
    """Връща (нова тема, нов payload doc, нови bytes, стъпки за trace).

    Пази изходния payload непроменен ако няма нито една трансформация."""
    steps: list[str] = []
    new_topic = topic
    if spec.topic_template:
        new_topic = render_template(spec.topic_template, topic, payload_doc)
        steps.append(f"тема: {topic} → {new_topic}")

    doc = payload_doc
    changed = False
    if spec.set_fields or spec.remove_fields or spec.add_envelope:
        if not isinstance(payload_doc, dict):
            # не-JSON payload + трансформация → обвиваме текста
            base: dict = {}
            if isinstance(payload_doc, str):
                base["text"] = payload_doc
            doc = base
        else:
            doc = json.loads(json.dumps(payload_doc))  # дълбоко копие
        changed = True

    for path, value in spec.set_fields.items():
        _set_field(doc, path, value)
        steps.append(f"set: {path} = {json.dumps(value, ensure_ascii=False)}")
    for path in spec.remove_fields:
        _remove_field(doc, path)
        steps.append(f"remove: {path}")
    if spec.add_envelope:
        doc = {
            "envelope": {
                "original_topic": topic,
                "rule_applied": True,
            },
            "payload": doc,
        }
        steps.append("envelope: оригиналът е обвит в envelope.payload")

    out_bytes = payload_bytes
    if changed:
        out_bytes = json.dumps(doc, ensure_ascii=False, default=str).encode()
        if len(out_bytes) > MAX_OUTPUT_BYTES:
            raise TransformError(
                f"резултатът надвишава лимита ({len(out_bytes)} > {MAX_OUTPUT_BYTES} B)"
            )
    if len(payload_bytes) > MAX_INPUT_BYTES:
        raise TransformError(f"входният payload надвишава {MAX_INPUT_BYTES} B")
    return new_topic, doc, out_bytes, steps
