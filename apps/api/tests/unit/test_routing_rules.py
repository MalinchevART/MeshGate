"""Модулни тестове на routing engine-а (чисти функции, без I/O)."""

import pytest

from app.routing.engine import evaluate
from app.routing.match import (
    PathError,
    get_path,
    parse_path,
    payload_matches,
    term_matches,
    topic_matches,
)
from app.routing.model import (
    Conditions,
    DestinationSpec,
    PayloadConditions,
    PayloadTerm,
    RuleDefinition,
    SourceSpec,
    TopicConditions,
    TransformSpec,
)
from app.routing.transform import TransformError, apply_transform, render_template


# ---------- path парсер ----------

def test_parse_path_valid_and_invalid():
    assert parse_path("$.a.b") == ["a", "b"]
    assert parse_path("$.items[0].name") == ["items", 0, "name"]
    assert parse_path("$") == []
    with pytest.raises(PathError):
        parse_path("a.b")          # без $ 
    with pytest.raises(PathError):
        parse_path("$.a.*")        # wildcard не се поддържа в P0
    with pytest.raises(PathError):
        parse_path("$.a[-1]")


def test_get_path_nested_and_missing():
    doc = {"telemetry": {"battery": 17}, "items": [{"code": "x"}]}
    assert get_path(doc, "$.telemetry.battery") == (True, 17)
    assert get_path(doc, "$.items[0].code") == (True, "x")
    assert get_path(doc, "$.telemetry.temp") == (False, None)
    assert get_path(doc, "$.items[5]") == (False, None)
    assert get_path(doc, "$.items.code") == (False, None)  # навигация през лист
    assert get_path([1, 2], "$[1]") == (True, 2)


# ---------- payload условия ----------

def test_term_operators():
    doc = {"battery": 15, "name": "node-3", "tags": ["a", "b"]}
    assert term_matches(PayloadTerm(path="$.battery", op="lt", value=20), doc)[0]
    assert not term_matches(PayloadTerm(path="$.battery", op="lt", value="x"), doc)[0]
    assert term_matches(PayloadTerm(path="$.name", op="eq", value="node-3"), doc)[0]
    assert term_matches(PayloadTerm(path="$.tags", op="contains", value="a"), doc)[0]
    assert term_matches(PayloadTerm(path="$.tags", op="exists"), doc)[0]
    assert term_matches(PayloadTerm(path="$.missing", op="exists"), doc)[0] is False


def test_payload_matches_all_any_and_non_json():
    battery_low = PayloadTerm(path="$.battery", op="lt", value=20)
    named = PayloadTerm(path="$.name", op="exists")
    doc = {"battery": 15}
    ok, _ = payload_matches(PayloadConditions(mode="all", terms=[battery_low, named]), doc)
    assert not ok  # name липсва
    ok, _ = payload_matches(PayloadConditions(mode="any", terms=[battery_low, named]), doc)
    assert ok
    ok, reasons = payload_matches(PayloadConditions(terms=[battery_low]), "само текст")
    assert not ok and any("не е JSON" in r for r in reasons)


# ---------- topic условия ----------

def test_topic_matches_include_exclude_priority():
    conds = TopicConditions(include=["mesh/+/up"], exclude=["mesh/emul/+/up"])
    ok, why = topic_matches(conds, "mesh/emul/3/up")
    assert not ok and "exclude" in why
    ok, _ = topic_matches(conds, "mesh/n1/up")
    assert ok


# ---------- трансформации ----------

def test_render_template_variants():
    doc = {"node": "n1", "telemetry": {"battery": 15}}
    assert render_template("{topic}", "a/b/c", doc) == "a/b/c"
    assert render_template("{topic_suffix[1]}", "a/b/c", doc) == "b/c"
    assert render_template("alerts/{topic_tokens[2]}", "mesh/emul/n1/up", doc) == "alerts/n1"
    assert render_template("x/{payload.node}", "t", doc) == "x/n1"
    assert render_template("b/{payload.telemetry.battery}", "t", doc) == "b/15"
    with pytest.raises(TransformError):
        render_template("{topic_tokens[9]}", "a/b", doc)
    with pytest.raises(TransformError):
        render_template("{payload.missing}", "a", doc)


def test_apply_transform_set_remove_envelope():
    spec = TransformSpec(
        topic_template="out/{topic_tokens[2]}",
        set_fields={"severity": "warning", "meta.rule": "r1"},
        remove_fields=["raw"],
        add_envelope=False,
    )
    doc = {"raw": "x", "battery": 15}
    topic, new_doc, raw, steps = apply_transform(spec, "mesh/emul/n1/up", doc, b"{}")
    assert topic == "out/n1"
    assert new_doc == {"battery": 15, "severity": "warning", "meta": {"rule": "r1"}}
    assert b"battery" in raw
    assert any("тема:" in s for s in steps)

    env = TransformSpec(add_envelope=True)
    topic, new_doc, raw, _ = apply_transform(env, "a/b", {"v": 1}, b"{}")
    assert new_doc["envelope"]["original_topic"] == "a/b"
    assert new_doc["payload"] == {"v": 1}


def test_apply_transform_passthrough_when_empty():
    spec = TransformSpec()
    payload = b'{"a":1}'
    topic, doc, raw, steps = apply_transform(spec, "a/b", {"a": 1}, payload)
    assert topic == "a/b" and raw == payload and doc == {"a": 1} and steps == []


# ---------- engine: evaluate ----------

def _rule(**kw) -> RuleDefinition:
    base = dict(
        name="r1",
        priority=100,
        enabled=True,
        source=SourceSpec(topic_filter="mesh/#"),
        conditions=Conditions(topic=TopicConditions(include=["mesh/+/+/up"])),
        destinations=[DestinationSpec(target="local", topic_template="copy/{topic}")],
    )
    base.update(kw)
    return RuleDefinition(**base)


def _eval(rules, topic, payload_doc, origin="local"):
    import json as _json

    raw = _json.dumps(payload_doc).encode() if isinstance(payload_doc, dict) else str(payload_doc).encode()
    return evaluate(rules, topic, raw, payload_doc, origin)


def test_evaluate_match_with_trace():
    traces = _eval([_rule()], "mesh/emul/n1/up", {"battery": 15})
    assert len(traces) == 1
    t = traces[0]
    assert t.decision == "match_forward"
    assert t.outputs[0].topic == "copy/mesh/emul/n1/up"
    assert any("topic условия" in s["step"] for s in t.steps)
    assert t.input_topic == "mesh/emul/n1/up"


def test_evaluate_no_match_topic_and_payload():
    assert _eval([_rule()], "other/topic", {})[0].decision == "no_match"
    rule = _rule(
        conditions=Conditions(
            topic=TopicConditions(include=["mesh/+/up"]),
            payload=PayloadConditions(terms=[PayloadTerm(path="$.battery", op="lt", value=20)]),
        )
    )
    assert _eval([rule], "mesh/emul/n1/up", {"battery": 80})[0].decision == "no_match"
    # не-JSON payload: условията не могат да минат
    assert _eval([rule], "mesh/emul/n1/up", "плътен текст")[0].decision == "no_match"


def test_evaluate_disabled_and_loop_marker():
    assert _eval([_rule(enabled=False)], "mesh/emul/n1/up", {})[0].decision == "skipped_disabled"
    assert _eval([_rule()], "mesh/emul/n1/up", {}, origin="routing:xyz") == []
    # bridge:* вече се ОБРАБОТВА (R2) — виж тестовете за suppression долу


def test_evaluate_first_match_stops_all_match_continues():
    r1 = _rule(name="r1", priority=10)
    r2 = _rule(name="r2", priority=20)
    traces = _eval([r2, r1], "mesh/emul/n1/up", {})  # r1 е с по-висок приоритет
    assert [t.rule_name for t in traces] == ["r1"]  # first_match по подразбиране
    traces = _eval([_rule(name="r1", priority=10, execution_mode="all_match"),
                    _rule(name="r2", priority=20, execution_mode="all_match")],
                   "mesh/emul/n1/up", {})
    assert [t.rule_name for t in traces] == ["r1", "r2"]


def test_evaluate_transform_error_is_recorded_not_raised():
    bad = _rule(transform=TransformSpec(topic_template="x/{topic_tokens[99]}"))
    t = _eval([bad], "mesh/emul/n1/up", {})[0]
    assert t.decision == "error"
    assert "токени" in t.error


def test_evaluate_multiple_destinations():
    rule = _rule(
        destinations=[
            DestinationSpec(target="local", topic_template="a/{topic}"),
            DestinationSpec(target="bridge:00000000-0000-0000-0000-000000000000",
                            topic_template="b/{topic}"),
        ]
    )
    t = _eval([rule], "mesh/emul/n1/up", {})[0]
    assert [o.topic for o in t.outputs] == ["a/mesh/emul/n1/up", "b/mesh/emul/n1/up"]


def test_evaluate_destination_template_uses_transformed_message():
    rule = _rule(
        transform=TransformSpec(topic_template="out/{topic_tokens[2]}"),
        destinations=[DestinationSpec(target="local", topic_template="{topic}/flag")],
    )
    t = _eval([rule], "mesh/emul/n1/up", {})[0]
    assert t.outputs[0].topic == "out/n1/flag"


# ---------- R2: входящ произход (bridge:*) и защита от връщане към същия мост ----------

def test_bridge_origin_processes_but_blocks_same_bridge_destination():
    ghost = "00000000-dead-beef-0000-00000000cafe"
    rule = _rule(
        name="r-in",
        destinations=[
            DestinationSpec(target=f"bridge:{ghost}", topic_template="x/{topic}"),
            DestinationSpec(target="local", topic_template="ok/{topic}"),
        ],
    )
    # донесено от друг мост: обработва се изцяло
    t = _eval([rule], "mesh/emul/n1/up", {}, origin=f"bridge:other-bridge")[0]
    assert t.decision == "match_forward"
    assert [o.target for o in t.outputs] == [f"bridge:{ghost}", "local"]
    # донесено от СЪЩИЯ мост: връщането към него се пресича, другите дестинации минават
    t2 = _eval([rule], "mesh/emul/n1/up", {}, origin=f"bridge:{ghost}")[0]
    assert t2.decision == "match_forward"
    assert [o.target for o in t2.outputs] == ["local"]
    assert any("пресечена" in s["step"] for s in t2.steps)


def test_routing_origin_still_blocked():
    # нашите собствени routing маркери не се обработват (цикъл)
    assert _eval([_rule()], "mesh/emul/n1/up", {}, origin="routing:r1") == []

# ---- Т20 AND/OR групи ------------------------------------------------------

from app.routing.match import payload_matches
from app.routing.model import PayloadConditions, PayloadGroup, PayloadTerm


def _t(path, op, value):
    return PayloadTerm(path=path, op=op, value=value)


def test_group_any_nested_three_levels():
    # top all: [battery>=10, GROUP any: [text exists, GROUP all: [snr>0, GROUP any: [a=1, b=2]]]]
    deep = PayloadGroup(mode="any", terms=[
        _t("$.a", "eq", 1), _t("$.b", "eq", 2)])
    mid = PayloadGroup(mode="all", terms=[_t("$.snr", "gt", 0), deep])
    top = PayloadGroup(mode="any", terms=[_t("$.battery", "gte", 10), mid])
    conds = PayloadConditions(mode="all", terms=[top])
    ok, why = payload_matches(conds, {"snr": 5, "b": 2})
    assert ok, why  # дълбоката any група пасва през b=2


def test_group_any_fails_when_no_branch():
    g = PayloadGroup(mode="any", terms=[_t("$.x", "eq", 1), _t("$.y", "eq", 2)])
    conds = PayloadConditions(mode="all", terms=[g])
    ok, why = payload_matches(conds, {"z": 3})
    assert not ok


def test_empty_group_passes_neutrally():
    conds = PayloadConditions(mode="all", terms=[
        PayloadGroup(mode="all"), _t("$.battery", "gte", 10)])
    ok, why = payload_matches(conds, {"battery": 50})
    assert ok, why  # празната група е неутрална


def test_unparseable_payload_configurable():
    conds = PayloadConditions(mode="all", terms=[_t("$.a", "eq", 1)])
    ok, _ = payload_matches(conds, "не-е-json")
    assert not ok  # default no_match
    conds2 = PayloadConditions(mode="all", terms=[_t("$.a", "eq", 1)],
                               on_unparseable="match")
    ok2, why2 = payload_matches(conds2, "не-е-json")
    assert ok2  # конфигуриран match (по тема)


def test_flat_terms_still_work_backward_compatible():
    conds = PayloadConditions(mode="all", terms=[_t("$.battery", "lt", 20)])
    ok, _ = payload_matches(conds, {"battery": 5})
    assert ok

# ---- Т22 разклонения: per-клонова error политика ---------------------------

from app.routing.model import DestinationSpec, ErrorPolicy, RetrySpec


def _rule_with_branches():
    """Правило с 2 клона: клон A — без политика (правило-та), клон B —
    своя (без dead-letter, halt)."""
    from app.routing.model import RuleDefinition, SourceSpec, TopicConditions, PayloadConditions, TransformSpec
    return RuleDefinition(
        name="branches",
        source=SourceSpec(),
        conditions=Conditions(),
        transform=TransformSpec(),
        destinations=[
            DestinationSpec(id="A", topic_template="out/a"),
            DestinationSpec(id="B", topic_template="out/b",
                            error_policy=ErrorPolicy(
                                on_destination_failure="halt",
                                retry=RetrySpec(max=0, backoff_ms=100),
                                dead_letter=False)),
        ],
    )


def test_branch_policy_is_optional_and_defaults_to_none():
    r = _rule_with_branches()
    assert r.destinations[0].error_policy is None
    assert r.destinations[1].error_policy is not None
    assert r.destinations[1].error_policy.dead_letter is False


def test_branch_policy_survives_serialization():
    r = _rule_with_branches()
    from app.routing.model import RuleDefinition
    r2 = RuleDefinition(**r.model_dump())
    assert r2.destinations[1].error_policy.on_destination_failure == "halt"
    assert r2.destinations[0].error_policy is None


def test_flat_rule_without_branch_policy_unchanged():
    """Обратна съвместимост: старо правило без per-клонови политики."""
    r = _rule_with_branches()
    r.destinations[1].error_policy = None
    from app.routing.model import RuleDefinition
    r2 = RuleDefinition(**r.model_dump())
    assert all(d.error_policy is None for d in r2.destinations)

# ---- Т25 приоритетна опашка -------------------------------------------------

from app.routing.service import classify_priority


def test_classify_normal_default():
    assert classify_priority(None, {}) == "normal"
    assert classify_priority("normal", {"severity": "critical"}) == "normal"


def test_classify_node_priority_wins():
    assert classify_priority("urgent", {}) == "urgent"
    assert classify_priority("critical", {}) == "critical"


def test_classify_auto_from_severity():
    assert classify_priority("auto", {"severity": "critical"}) == "urgent"
    assert classify_priority("auto", {"decoded": {"severity": "critical"}}) == "urgent"
    assert classify_priority("auto", {"severity": "info"}) == "normal"
    assert classify_priority("auto", "не-JSON") == "normal"
    assert classify_priority("auto", {}) == "normal"


from app.routing.service import should_hold_back


def test_hold_back_only_normal_on_holding_node():
    assert should_hold_back("normal", "!ABC123", {"!abc123": True}) is True


def test_hold_back_urgent_and_critical_pass():
    assert should_hold_back("urgent", "!abc", {"!abc": True}) is False
    assert should_hold_back("critical", "!abc", {"!abc": True}) is False


def test_hold_back_unknown_or_missing_node_passes():
    assert should_hold_back("normal", "!other", {"!abc": True}) is False
    assert should_hold_back("normal", None, {"!abc": True}) is False
    assert should_hold_back("normal", "!abc", {}) is False
