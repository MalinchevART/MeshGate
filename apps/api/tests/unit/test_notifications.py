"""Модулни тестове на двигателите за известия (docs/12)."""
import asyncio
import json
import time

import pytest

from app.notify.engine import (
    NotificationEngine, build_digest, config_valid, in_quiet_hours,
    render_message,
)


def test_render_message_variants():
    plain = render_message("alerts/battery/!abcd", None, "local")
    assert "alerts/battery/!abcd" in plain

    decoded = {"text": "помощ", "node": "!abcd1234", "channel": "LongFast"}
    msg = render_message("msh/EU_868/2/e/LongFast/!abcd1234", decoded, "bridge:1")
    assert "помощ" in msg
    assert "възел !abcd1234" in msg
    assert "канал LongFast" in msg
    assert "via bridge:1" in msg

    tele = {"node": "!ab12", "battery": 7, "snr": -9.5}
    msg2 = render_message("t/x", tele, "local")
    assert "батерия 7%" in msg2
    assert "SNR" in msg2


def test_render_template_variables():
    decoded = {"text": "внимание", "node": "!ab12", "channel": "LongFast",
               "battery": 7, "snr": -9.5}
    out = render_message(
        "msh/emul/2/e/LongFast/!ab12", decoded, "bridge:2",
        template="⚠ {node} ({channel}): {text} · бат. {battery} · SNR {snr} · {origin}")
    assert "⚠ !ab12 (LongFast): внимание" in out
    assert "бат. 7%" in out
    assert "SNR -9.5 dB" in out
    assert "bridge:2" in out

    # липсващи стойности → тире; неизвестен placeholder остава като текст
    out2 = render_message("t/y", None, "local", template="{node} {text} {battery} {неизвестно}")
    assert out2 == "— — — {неизвестно}"


def test_config_valid():
    ok, _ = config_valid("telegram", {"bot_token": "t", "chat_id": "1"})
    assert ok
    ok, why = config_valid("telegram", {"bot_token": "t"})
    assert not ok and "chat_id" in why
    ok, _ = config_valid("email", {"to": "a@b.c"})
    assert ok
    ok, _ = config_valid("email", {"to": "не-поща"})
    assert not ok
    ok, _ = config_valid("webhook", {"url": "https://x.example/hook"})
    assert ok
    ok, _ = config_valid("webhook", {"url": "ftp://x"})
    assert not ok
    ok, _ = config_valid("whatsapp", {"phone": "+359888123456", "apikey": "k"})
    assert ok
    ok, why = config_valid("whatsapp", {"phone": "0888abc", "apikey": "k"})
    assert not ok and "phone" in why
    ok, why = config_valid("whatsapp", {"phone": "+359888"})
    assert not ok and "apikey" in why
    ok, _ = config_valid("pigeon", {})
    assert not ok


class _CaptureEngine(NotificationEngine):
    """Engine без база: _log събира в списък, _send записва какво би тръгнало."""

    def __init__(self):
        super().__init__(pool=None)
        self.sent: list[tuple[dict, str]] = []
        self.logged: list[tuple[str, str | None]] = []

    async def _log(self, ch, topic, message, status, error):
        self.logged.append((status, error))

    async def _send(self, ch, topic, message):
        self.sent.append((ch, message))


def _ch(cid="c1", pattern="alerts/#", interval=30):
    return {
        "id": cid, "name": cid, "kind": "webhook", "topic_pattern": pattern,
        "config": {"url": "https://x.example/h"}, "min_interval_s": interval,
        "enabled": True,
    }


@pytest.mark.asyncio
async def test_dispatch_matching_rate_limit_and_dedupe():
    e = _CaptureEngine()
    e.channels = {"c1": _ch(), "c2": _ch(cid="c2", pattern="msh/#")}
    await e._dispatch("alerts/battery/!a", {"battery": 5}, "local")
    assert len(e.sent) == 1 and "alerts/battery/!a" in e.sent[0][1]

    # несъответстваща тема не праща нищо
    await e._dispatch("mesh/other/x", None, "local")
    assert len(e.sent) == 1

    # дубликат в рамките на минутата → skipped
    await e._dispatch("alerts/battery/!a", {"battery": 5}, "local")
    assert len(e.sent) == 1
    assert any(s == "skipped" for s, _ in e.logged)

    # различно съдържание, но анти-спам интервалът още не е минал → skipped
    await e._dispatch("alerts/battery/!b", {"battery": 4}, "local")
    assert len(e.sent) == 1

    # изтичане на анти-спам прозореца → пак се изпраща
    e._last_sent["c1"] = 0.0
    await e._dispatch("alerts/battery/!b", {"battery": 4}, "local")
    assert len(e.sent) == 2


@pytest.mark.asyncio
async def test_failed_channel_does_not_stop_others():
    e = _CaptureEngine()
    e.channels = {"bad": _ch(cid="bad"), "good": _ch(cid="good")}

    async def boom(ch, topic, message):
        if ch["id"] == "bad":
            raise RuntimeError("каналът е мъртъв")
        e.sent.append((ch, message))

    e._send = boom  # type: ignore[method-assign]
    await e._dispatch("alerts/x", None, "local")
    assert len(e.sent) == 1 and e.sent[0][0]["id"] == "good"
    assert any(s == "failed" and err and "мъртъв" in err for s, err in e.logged)


@pytest.mark.asyncio
async def test_handle_local_never_blocks_without_channels():
    e = _CaptureEngine()
    e.handle_local("alerts/x", None, "local")  # няма канали → no-op
    assert e._queue.qsize() == 0


async def test_telegram_sender_payload():
    """Webhook/telegram senders ползват httpx client с правия URL и тяло."""
    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True})

    # базовият engine: _CaptureEngine override-ва _send и не би пратил нищо
    e = NotificationEngine(pool=None)
    e._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=5
    )
    ch = {
        "id": "tg", "name": "tg", "kind": "telegram", "topic_pattern": "alerts/#",
        "config": {"bot_token": "123:ABC", "chat_id": "42"},
        "min_interval_s": 0, "enabled": True,
    }
    await e._send(ch, "alerts/x", "здравей")
    await e._client.aclose()
    assert captured["url"] == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert captured["body"] == {"chat_id": "42", "text": "здравей"}


@pytest.mark.asyncio
async def test_whatsapp_sender_callmebot():
    """WhatsApp през CallMeBot: GET с phone/apikey/text (образецът от NetSight)."""
    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text="ok")

    e = NotificationEngine(pool=None)
    e._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=5
    )
    ch = {
        "id": "wa", "name": "wa", "kind": "whatsapp", "topic_pattern": "alerts/#",
        "config": {"phone": "+359888123456", "apikey": "k1"},
        "min_interval_s": 0, "enabled": True,
    }
    await e._send(ch, "alerts/x", "⚠ батерия 5%")
    assert captured["url"].startswith("https://api.callmebot.com/whatsapp.php")
    assert "phone=359888123456" in captured["url"]  # + се маха
    assert "apikey=k1" in captured["url"]
    assert "text=%E2%9A%A0" in captured["url"]  # URL-encode на съобщението

    # без phone/apikey → ясна грешка, не мрежово повикване
    with pytest.raises(ValueError, match="phone/apikey"):
        await e._send({**ch, "config": {"phone": ""}}, "alerts/x", "m")
    await e._client.aclose()


@pytest.mark.asyncio
async def test_dispatch_uses_channel_template():
    """Всеки канал си рендерира съобщението със собствения шаблон."""
    e = _CaptureEngine()
    e.channels = {
        "c1": {**_ch(), "template": "TG: {node} → {text}"},
        "c2": {**_ch(cid="c2"), "template": None},
    }
    await e._dispatch("alerts/battery/!a", {"node": "!a", "text": "пада"}, "local")
    msgs = {ch["id"]: m for ch, m in e.sent}
    assert msgs["c1"] == "TG: !a → пада"
    assert "MeshGate · alerts/battery/!a" in msgs["c2"]


# ---------- трети срез: важност + тихи часове ----------
def _at(hh: int, mm: int):
    t = time.localtime()
    return time.struct_time((t.tm_year, t.tm_mon, t.tm_mday, hh, mm, 0,
                             t.tm_wday, t.tm_yday, -1))


def test_in_quiet_hours_window_and_midnight_cross():
    cfg = {"quiet_hours": {"start": "23:00", "end": "07:00"}}
    assert in_quiet_hours(cfg, _at(23, 30)) is True   # вечерта
    assert in_quiet_hours(cfg, _at(3, 0)) is True     # през нощта (през полунощ)
    assert in_quiet_hours(cfg, _at(12, 0)) is False   # обед
    cfg2 = {"quiet_hours": {"start": "13:00", "end": "14:00"}}
    assert in_quiet_hours(cfg2, _at(13, 30)) is True
    assert in_quiet_hours(cfg2, _at(14, 0)) is False  # краят е изключителен
    assert in_quiet_hours({}, _at(3, 0)) is False     # без тихи часове
    assert in_quiet_hours({"quiet_hours": {"start": "лошо", "end": "07:00"}},
                          _at(3, 0)) is False          # боклук → неактивни


@pytest.mark.asyncio
async def test_severity_gate_skips_below_channel_level():
    e = _CaptureEngine()
    e.channels = {"vip": {**_ch(cid="vip"), "severity": "important"}}
    # info съобщение → под нивото → skipped, не се праща
    await e._dispatch("alerts/x", {"severity": "info", "battery": 5}, "local")
    assert e.sent == []
    assert any(s == "skipped" and "под нивото" in (err or "")
               for s, err in e.logged)
    # critical → минава
    e._last_sent.clear()
    await e._dispatch("alerts/y", {"severity": "critical", "battery": 3}, "local")
    assert len(e.sent) == 1


@pytest.mark.asyncio
async def test_quiet_hours_mute_all_but_critical():
    e = _CaptureEngine()
    # „сега" е в тихи часове: прозорец 00:00–23:59 хваща всичко
    e.channels = {"night": {**_ch(cid="night", interval=0),
                            "config": {"quiet_hours": {"start": "00:00", "end": "23:59"}}}}
    await e._dispatch("alerts/x", {"battery": 5}, "local")  # info → тихо
    assert e.sent == [] and any("тиши часове" in (err or "") or "тихи часове" in (err or "")
                                for s, err in e.logged)
    e._last_sent.clear()
    e._seen.clear()
    await e._dispatch("alerts/y", {"severity": "critical"}, "local")
    assert len(e.sent) == 1  # критичното минава и нощем


# ---------- сутрешен бриф (docs/15 Вълна 1) ----------

def test_digest_message_shape():
    """build_digest работи без база — с подправен pool връща пълния текст."""
    import datetime as _dt

    class _FakePool:
        async def fetchval(self, q, *a):
            return 1234

        async def fetch(self, q, *a):
            if "battery" in q:
                return [{"node": "!ab12", "bat": 7, "total": 5}]
            if "regexp_match" in q and "count(*)" in q.lower():
                return [{"ch": "LongFast", "n": 500}]
            return []

    text = asyncio.run(build_digest(_FakePool()))
    assert text.startswith("☕ MeshGate бриф ·")
    assert "пакети: 1234" in text
    assert "!ab12 7%" in text          # слаба батерия
    assert "+2 още" in text            # само 3 се показват, останалите — брой
    assert "мъртви букви: 1234" in text
    # тихият случай: без батерии/мъртви букви → успокояващ ред
    class _CalmPool(_FakePool):
        async def fetch(self, q, *a):
            return []

        async def fetchval(self, q, *a):
            # само общия брой пакети е ненулев; мъртви букви = 0
            return 1234 if "FROM packets WHERE ts" in q else 0

    calm = asyncio.run(build_digest(_CalmPool()))
    assert "всичко е спокойно" in calm


@pytest.mark.asyncio
async def test_digest_tick_logic(monkeypatch):
    """_digest_tick: hour-match, веднъж на ден, рестарт-предпазка през
    журнала, боклучив час не спира другите, успех маркира деня."""
    import time as _time

    e = _CaptureEngine()
    e._digest_sent = {}
    e._digest_tries = {}

    async def fake_digest(pool):
        return "БРИФ"

    async def fake_send(ch, topic, message):
        if ch["id"] == "dead":
            raise RuntimeError("каналът е мъртъв")
        e.sent.append((ch, message))

    async def fake_log(ch, topic, message, status, error):
        e.logged.append((ch["id"], status))

    monkeypatch.setattr("app.notify.engine.build_digest", fake_digest)
    e._send = fake_send
    e._log = fake_log

    class _Pool:
        async def fetchval(self, q, *a):
            # рестарт-предпазка: канал 'already' вече е пращал днес
            return 1 if a and str(a[0]) == "already" else 0

    e.pool = _Pool()
    e.channels = {
        "ok": {"id": "ok", "config": {"digest_hour": 8}, "kind": "telegram"},
        "off": {"id": "off", "config": {"digest_hour": 9}, "kind": "telegram"},
        "bad": {"id": "bad", "config": {"digest_hour": "лошо"}, "kind": "telegram"},
        "dead": {"id": "dead", "config": {"digest_hour": 8}, "kind": "telegram"},
        "already": {"id": "already", "config": {"digest_hour": 8}, "kind": "telegram"},
    }

    now = _time.struct_time((2026, 10, 24, 8, 5, 0, 5, 297, -1))
    await e._digest_tick(now)
    sent_ids = [ch["id"] for ch, _ in e.sent]
    # само 'ok' минава: off е друг час, bad е боклук, dead се провали, already е пращал
    assert sent_ids == ["ok"]
    assert ("dead", "failed") in e.logged
    assert e._digest_sent == {"ok": "2026-10-24", "already": "2026-10-24"}  # failed не маркира деня

    # втор tick същия час: 'ok'/'already' са маркирани; 'dead' опитва пак
    # (без маркиране на деня) и пак се проваля — но с ограничение 3 опита
    e.sent.clear()
    e.logged.clear()
    await e._digest_tick(now)
    assert e.sent == []  # dead пак гръмна (нищо не е изпратено)
    assert ("dead", "failed") in e.logged
    # трети и четвърти tick: след MAX_DIGEST_TRIES 'dead' спира да опитва
    await e._digest_tick(now)
    e.logged.clear()
    await e._digest_tick(now)
    assert ("dead", "failed") not in e.logged  # изчерпа опитите за днес
