"""Чиста логика за съвпадение на условия — без I/O, тестваема на единица."""

import re
from typing import Any

from ..bridge.rules import mqtt_match
from .model import PayloadConditions, PayloadGroup, PayloadTerm, TopicConditions

# $.a.b, $.arr[0].c —mini path парсер (без wildcards; пълен JSONPath е P1 с ADR)
_PATH_RE = re.compile(
    r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*$"
)


class PathError(ValueError):
    pass


def parse_path(path: str) -> list[str | int]:
    if not _PATH_RE.match(path):
        raise PathError(f"невалиден path: {path!r} (очаква се $.a.b[0])")
    out: list[str | int] = []
    for part in re.findall(r"\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\]", path):
        if part.startswith("."):
            out.append(part[1:])
        else:
            out.append(int(part[1:-1]))
    return out


def get_path(doc: Any, path: str) -> tuple[bool, Any]:
    """Връща (намерен ли е, стойност). Липсващ/невалиден път → (False, None)."""
    try:
        parts = parse_path(path)
    except PathError:
        return False, None
    cur = doc
    for p in parts:
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur):
                return False, None
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return False, None
            cur = cur[p]
    return True, cur


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def term_matches(term: PayloadTerm, doc: Any) -> tuple[bool, str]:
    """Едно payload условие → (премина ли, причина)."""
    found, val = get_path(doc, term.path)
    if term.op == "exists":
        return (found, f"{term.path}: {'съществува' if found else 'липсва'}")
    if not found:
        return False, f"{term.path}: липсващ path"
    if term.op in ("gt", "gte", "lt", "lte"):
        a, b = _num(val), _num(term.value)
        if a is None or b is None:
            return False, f"{term.path}: числово сравнение с нечислова стойност"
        ok = {
            "gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b,
        }[term.op]
        return ok, f"{term.path}({val}) {term.op} {term.value}"
    if term.op == "eq":
        return val == term.value, f"{term.path}({val!r}) == {term.value!r}"
    if term.op == "ne":
        return val != term.value, f"{term.path}({val!r}) != {term.value!r}"
    if term.op == "contains":
        ok = (
            term.value in val
            if isinstance(val, (str, list, tuple))
            else term.value in str(val)
        )
        return ok, f"{term.path} съдържа {term.value!r}"
    return False, f"непознат оператор {term.op}"


def node_matches(node: PayloadTerm | PayloadGroup, doc: Any,
                 depth: int = 0) -> tuple[bool, list[str]]:
    """Т20: термин ИЛИ група → (преминал ли, причини). Групите са рекурсивни
    (all/any); празна група пасва винаги (неутрален елемент)."""
    if not isinstance(node, PayloadGroup):
        return term_matches(node, doc)
    pad = "  " * depth
    if not node.terms:
        return True, [f"{pad}празна група ({node.mode}) — пасва"]
    results: list[bool] = []
    reasons: list[str] = [f"{pad}[група {node.mode.upper()}]"]
    for t in node.terms:
        ok, why = node_matches(t, doc, depth + 1)
        results.append(ok)
        reasons.extend(why if isinstance(why, list) else [why])
    passed = all(results) if node.mode == "all" else any(results)
    reasons.append(f"{pad}→ групата {'пасва' if passed else 'не пасва'}")
    return passed, reasons


def payload_matches(conds: PayloadConditions, doc: Any) -> tuple[bool, list[str]]:
    """Payload условия (вкл. Т20 групи) → (преминали ли, причини)."""
    if not conds.terms:
        return True, ["без payload условия"]
    if not isinstance(doc, (dict, list)):
        # Т20: конфигурирано поведение при непарсебъл payload
        if conds.on_unparseable == "match":
            return True, ["payload не е JSON — по конфиг (match) се прилага само по тема"]
        return False, ["payload не е JSON обект/масив — условията не се прилагат"]
    reasons: list[str] = []
    results: list[bool] = []
    for t in conds.terms:
        ok, why = node_matches(t, doc)
        results.append(ok)
        reasons.extend(why if isinstance(why, list) else [why])
    passed = all(results) if conds.mode == "all" else any(results)
    return passed, reasons


def topic_matches(conds: TopicConditions, topic: str) -> tuple[bool, str]:
    """Include/exclude по MQTT шаблон; exclude има приоритет."""
    for pat in conds.exclude:
        if mqtt_match(pat, topic):
            return False, f"exclude: {pat}"
    if not conds.include:
        return True, "без include условия (всички теми)"
    for pat in conds.include:
        if mqtt_match(pat, topic):
            return True, f"include: {pat}"
    return False, "нищо от include не пасва"
