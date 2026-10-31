"""Модулни тестове на чистата bridge логика (без I/O)."""

from app.bridge.rules import (
    BridgePolicy,
    DedupeCache,
    Rule,
    SlidingWindowLimiter,
    map_topic,
    mqtt_match,
)


def test_mqtt_match_exact_and_wildcards():
    assert mqtt_match("mesh/a/up", "mesh/a/up")
    assert not mqtt_match("mesh/a/up", "mesh/b/up")
    assert mqtt_match("mesh/+/up", "mesh/x/up")
    assert not mqtt_match("mesh/+/up", "mesh/x/down")
    assert mqtt_match("mesh/#", "mesh/x/y/z")
    assert mqtt_match("#", "каквото/и/да/е")
    assert not mqtt_match("mesh/#", "other/x")


def test_default_deny_when_no_allow_rule_matches():
    policy = BridgePolicy(rules=[Rule(kind="allow", topic_pattern="mesh/+/up")])
    d = policy.decide("secret/zone", b"x", "text", "local")
    assert d.action == "reject"
    assert "default deny" in d.reason


def test_deny_rule_wins_by_priority():
    policy = BridgePolicy(
        rules=[
            Rule(kind="allow", topic_pattern="mesh/#", priority=100),
            Rule(kind="deny", topic_pattern="mesh/priv/#", priority=10, reason="лични данни"),
        ]
    )
    d = policy.decide("mesh/priv/secret", b"x", "text", "local")
    assert d.action == "reject" and "лични данни" in d.reason
    d2 = policy.decide("mesh/sensor/1", b"x", "text", "local")
    assert d2.action == "forward"


def test_payload_type_filter_only_when_known():
    policy = BridgePolicy(
        rules=[Rule(kind="allow", topic_pattern="mesh/#", payload_type="json")]
    )
    assert policy.decide("mesh/a", b"{}", "json", "local").action == "forward"
    d = policy.decide("mesh/a", b"\x00\x01", "binary", "local")
    assert d.action == "reject"


def test_origin_marker_blocks_loop():
    policy = BridgePolicy(rules=[Rule(kind="allow", topic_pattern="#")])
    d = policy.decide("mesh/a", b"x", "text", origin="bridge:abc")
    assert d.action == "loop_blocked" and "origin" in d.reason


def test_dedupe_blocks_immediate_reforward():
    policy = BridgePolicy(rules=[Rule(kind="allow", topic_pattern="#")])
    payload = b"same"
    assert policy.decide("mesh/a", payload, "text", "local").action == "forward"
    d = policy.decide("mesh/a", payload, "text", "local")
    assert d.action == "loop_blocked" and "dedupe" in d.reason
    # различен payload минава
    assert policy.decide("mesh/a", b"other", "text", "local").action == "forward"


def test_rate_limit():
    policy = BridgePolicy(
        rules=[Rule(kind="allow", topic_pattern="#")], rate_limit_per_min=2
    )
    assert policy.decide("t/1", b"1", "text", "local").action == "forward"
    assert policy.decide("t/2", b"2", "text", "local").action == "forward"
    d = policy.decide("t/3", b"3", "text", "local")
    assert d.action == "rate_limited"


def test_limiter_window_slides():
    lim = SlidingWindowLimiter(2)
    t0 = 1000.0
    assert lim.allow(t0) and lim.allow(t0 + 1)
    assert not lim.allow(t0 + 2)
    assert lim.allow(t0 + 61)


def test_map_topic_prefix():
    m = [{"from_prefix": "mesh", "to_prefix": "gw1/mesh"}]
    assert map_topic("mesh/a/up", m) == "gw1/mesh/a/up"
    assert map_topic("other/a", m) == "other/a"
    assert map_topic("mesh/a", [{"from_prefix": "mesh", "to_prefix": ""}]) == "a"
