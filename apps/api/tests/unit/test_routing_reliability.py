"""R2: retry / halt / dead-letter при доставка (docs/09 §R2, docs/07)."""
import json

import pytest

from app.routing.engine import Output, evaluate
from app.routing.model import ErrorPolicy, RetrySpec, RuleDefinition
from app.routing.service import RoutingEngine


def _rule(dest_count=1, ep=None):
    return RuleDefinition(
        name="rule-x",
        enabled=True,
        source={"topic_filter": "#"},
        conditions={"topic": {"include": ["in/#"]}},
        destinations=[
            {"type": "mqtt", "target": "local",
             "topic_template": f"alerts/{i}", "qos": 1, "retain": False}
            for i in range(dest_count)
        ],
        error_policy=ep or ErrorPolicy(),
    )


class _Engine(RoutingEngine):
    """Без база/брокер: _deliver отказва първите fail_times пъти (без
    deadletter темите), dead-letter публикации се хващат като JSON."""

    def __init__(self, fail_times=99):
        super().__init__(pool=None, bridge=None)
        self.fail_times = fail_times
        self.calls = 0
        self.dead_letters: list[dict] = []
        self.ok_topics: list[str] = []
        self.recorded: tuple[int, int] | None = None
        self.last_steps: list[dict] = []

    async def _deliver(self, rule_id, out):
        if out.topic.startswith("deadletter/"):
            self.dead_letters.append(json.loads(out.payload))
            return True, None
        self.calls += 1
        if self.calls <= self.fail_times:
            return False, "недостъпен"
        self.ok_topics.append(out.topic)
        return True, None

    async def _record(self, t, duration_ms, delivered, failed):
        self.recorded = (delivered, failed)
        self.last_steps = t.steps


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    e = _Engine(fail_times=1)
    e.rules = [_rule(ep=ErrorPolicy(retry=RetrySpec(max=2, backoff_ms=100)))]
    await e.handle_local("in/x", b"msg", None, "local")
    assert e.calls == 2
    assert e.recorded == (1, 0)
    assert e.ok_topics == ["alerts/0"]
    assert any("след 2 опита" in s["step"] for s in e.last_steps)


@pytest.mark.asyncio
async def test_dead_letter_after_exhausted_retries():
    e = _Engine(fail_times=99)
    e.rules = [_rule(ep=ErrorPolicy(retry=RetrySpec(max=1, backoff_ms=100),
                                   dead_letter=True))]
    await e.handle_local("in/x", b"msg-xyz", None, "local")
    assert e.calls == 2  # 1 + retry.max=1
    assert e.recorded == (0, 1)
    assert len(e.dead_letters) == 1
    dl = e.dead_letters[0]
    assert dl["rule"] == "rule-x"
    assert dl["target"] == "local"
    assert dl["topic"] == "alerts/0"
    assert dl["payload_b64"] == __import__("base64").b64encode(b"msg-xyz").decode()
    assert dl["error"] == "недостъпен"


@pytest.mark.asyncio
async def test_dead_letter_disabled_by_policy():
    e = _Engine(fail_times=99)
    e.rules = [_rule(ep=ErrorPolicy(retry=RetrySpec(max=0, backoff_ms=100),
                                   dead_letter=False))]
    await e.handle_local("in/x", b"msg", None, "local")
    assert e.calls == 1
    assert e.dead_letters == []


@pytest.mark.asyncio
async def test_halts_remaining_destinations_on_failure():
    e = _Engine(fail_times=99)
    e.rules = [_rule(dest_count=2,
                     ep=ErrorPolicy(retry=RetrySpec(max=0, backoff_ms=100),
                                    on_destination_failure="halt",
                                    dead_letter=False))]
    await e.handle_local("in/x", b"msg", None, "local")
    # първата дестинация се опитва веднъж и halt прескача втората
    assert e.calls == 1
    assert e.ok_topics == []


@pytest.mark.asyncio
async def test_continue_policy_tries_all_destinations():
    e = _Engine(fail_times=1)
    e.rules = [_rule(dest_count=2,
                     ep=ErrorPolicy(retry=RetrySpec(max=0, backoff_ms=100),
                                    on_destination_failure="continue",
                                    dead_letter=False))]
    await e.handle_local("in/x", b"msg", None, "local")
    assert e.calls == 2  # и двете дестинации се опитват
    assert e.recorded == (1, 1)  # втората минава (fail само първия път)


@pytest.mark.asyncio
async def test_backpressure_gives_up_honestly_when_slots_exhausted():
    """Бавни доставки не задръстват ingestion-а: изчерпани слотове → отказ."""
    from app.routing.service import RoutingEngine, DELIVERY_SLOT_WAIT_S

    e = _Engine(fail_times=0)
    # _Engine наследява RoutingEngine → има _slots; заемаме всичките
    for _ in range(16):
        await e._slots.acquire()
    ep = ErrorPolicy(retry=RetrySpec(max=2, backoff_ms=100), dead_letter=False)
    t = type("T", (), {"rule_id": "r1", "rule_name": "x", "error_policy": ep})()
    out = type("O", (), {"type": "mqtt", "target": "local", "topic": "t",
                         "qos": 0, "retain": False, "payload": b"p",
                         "dest_id": None})()
    ok, err, attempts = await e._deliver_with_retry(ep, t, out)
    assert ok is False and attempts == 0
    assert "backpressure" in (err or "")
    assert e.calls == 0  # нито един реален опит не е направен
    assert e.backpressured == 1


# ---------- R2 остатък: HTTP/webhook дестинация ----------

def _http_rule(url: str | None):
    return RuleDefinition(
        name="http-rule",
        enabled=True,
        source={"topic_filter": "#"},
        conditions={"topic": {"include": ["in/#"]}},
        destinations=[{
            "type": "http", "target": "http",
            "topic_template": "{topic}", "qos": 0, "retain": False,
            "url": url,
        }],
    )


def test_evaluate_http_destination_output():
    traces = evaluate([_http_rule("https://example.com/hook")],
                      "in/x", b'{"a":1}', {"a": 1}, "local")
    assert traces[0].decision == "match_forward"
    out = traces[0].outputs[0]
    assert out.type == "http"
    assert out.target == "https://example.com/hook"
    assert out.payload == b'{"a":1}'
    assert any("HTTP дестинация" in s["step"] for s in traces[0].steps)


def test_evaluate_http_destination_without_url_is_error():
    traces = evaluate([_http_rule(None)], "in/x", b"{}", {}, "local")
    assert traces[0].decision == "error"
    assert "без валиден url" in (traces[0].error or "")


@pytest.mark.asyncio
async def test_http_delivery_posts_payload_with_content_type():
    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        captured["ctype"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={"ok": True})

    e = RoutingEngine(pool=None, bridge=None)
    e.http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)
    out = Output(dest_id=None, type="http", target="https://n8n.local/hook",
                 topic="t", qos=0, retain=False, payload=b'{"text":"hey"}')
    ok, err = await e._deliver("r1", out)
    assert ok and err is None
    assert captured["url"] == "https://n8n.local/hook"
    assert captured["body"] == b'{"text":"hey"}'
    assert captured["ctype"] == "application/json"

    # текстов payload → text/plain (пътят към ntfy)
    out2 = Output(dest_id=None, type="http", target="https://ntfy.sh/x",
                  topic="t", qos=0, retain=False,
                  payload="съобщение".encode("utf-8"))
    ok2, _ = await e._deliver("r1", out2)
    assert ok2 and captured["ctype"] == "text/plain"

    # 500 → провал (и retry политиката го хваща отвън)
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    e.http = httpx.AsyncClient(transport=httpx.MockTransport(fail), timeout=5)
    ok3, err3 = await e._deliver("r1", out)
    assert not ok3 and "500" in str(err3)
    await e.http.aclose()
