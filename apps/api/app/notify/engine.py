"""Двигател за известия: мачване на теми → канали → изпращане + журнал."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import smtplib
import time
from email.message import EmailMessage

import asyncpg
import httpx

from ..bridge.rules import mqtt_match  # същото MQTT съвпадане като навсякъде
from ..config import settings

log = logging.getLogger("meshgate.notify")

QUEUE_MAX = 500
SEND_TIMEOUT_S = 10.0
DEDUPE_TTL_S = 60.0

# нива на важност: съобщение под нивото на канала се пропуска
SEVERITY_RANK = {"info": 0, "important": 1, "critical": 2}

# Сутрешен бриф (docs/15 Вълна 1): веднъж на ден, в зададения час на канал
# с config.digest_hour — ЕДНО обобщено съобщение спрямо последните 24 ч.
DIGEST_TICK_S = 60.0
# трайно повреден канал не бива да трупа failed запис всеки минут до края
# на часа — след толкова неуспешни опита за деня спира до утре
MAX_DIGEST_TRIES = 3


def week_norm_note(yesterday_snr: float | None, weekday_norm: float | None) -> str | None:
    """Т29: „спрямо седмичната норма" — вчера срещу медианата на същия
    ден от седмицата (предходни ~4 седмици). Чиста функция; None навсякъде
    = няма данни (брифът мълчи вместо да измисля)."""
    if yesterday_snr is None or weekday_norm is None:
        return None
    diff = yesterday_snr - weekday_norm
    arrow = "над" if diff >= 0 else "под"
    return (f"эфирът вчера беше {diff:+.1f} dB {arrow} седмичната норма "
            f"({weekday_norm:+.1f} dB)")


async def build_digest(pool) -> str:
    """Съдържанието на брифа — от самите данни на платформата (посл. 24 ч):
    трафик, активни/нови възли, тихи фаворити, слаби батерии, мъртви букви,
    топ канали. Никакви прогнози — измерено."""
    async def one(q: str, *a) -> object:
        return await pool.fetchval(q, *a)

    total = await one(
        "SELECT count(*) FROM packets WHERE ts > now() - interval '24 hours'")
    mesh_nodes = await one(
        "SELECT count(DISTINCT (regexp_match(topic, '(![0-9a-fA-F]+)$'))[1])"
        " FROM packets WHERE topic LIKE 'msh/%' AND ts > now() - interval '24 hours'")
    new_nodes = await one(
        "SELECT count(*) FROM devices"
        " WHERE first_seen_at > now() - interval '24 hours'"
        "   AND external_id LIKE '!%'")
    dead = await one(
        "SELECT count(*) FROM packets WHERE topic LIKE 'deadletter/%'"
        " AND ts > now() - interval '24 hours'")
    sent_notifs = await one(
        "SELECT count(*) FROM notification_log WHERE status = 'sent'"
        " AND ts > now() - interval '24 hours'")
    low_bat = await pool.fetch(
        "SELECT (e.payload->'decoded'->>'node') AS node,"
        " max((e.payload->'decoded'->>'battery')::numeric) AS bat,"
        " count(*) OVER() AS total"
        " FROM events e"
        " WHERE e.ts > now() - interval '24 hours'"
        "   AND (e.payload->'decoded'->>'battery') ~ '^[0-9]+(\\.[0-9]+)?$'"
        " GROUP BY 1 HAVING max((e.payload->'decoded'->>'battery')::numeric) < 25"
        " ORDER BY 2 LIMIT 5")
    top_ch = await pool.fetch(
        "SELECT (regexp_match(topic, 'msh/[^/]+/2/(?:e|c|json)/([^/]+)/'))[1] AS ch,"
        " count(*) AS n FROM packets"
        " WHERE topic LIKE 'msh/%' AND ts > now() - interval '24 hours'"
        "   AND regexp_match(topic, 'msh/[^/]+/2/(?:e|c|json)/([^/]+)/') IS NOT NULL"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 3")
    quiet = await pool.fetch(
        "SELECT external_id FROM devices"
        " WHERE external_id LIKE '!%'"
        "   AND last_seen_at < now() - interval '12 hours'"
        "   AND last_seen_at > now() - interval '48 hours'"
        " ORDER BY last_seen_at LIMIT 3")

    # Т29: ефирът вчера спрямо седмичната норма (медиани от events SNR)
    y_snr = await one(
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY"
        " (payload->'decoded'->>'snr')::numeric)"
        " FROM events"
        " WHERE ts >= date_trunc('day', now()) - interval '24 hours'"
        "   AND ts < date_trunc('day', now())"
        "   AND payload->'decoded'->>'snr' IS NOT NULL")
    w_norm = await one(
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY"
        " (payload->'decoded'->>'snr')::numeric)"
        " FROM events"
        " WHERE ts >= date_trunc('day', now()) - interval '28 days'"
        "   AND ts < date_trunc('day', now()) - interval '24 hours'"
        "   AND extract(isodow from ts) = extract(isodow from now())"
        "   AND payload->'decoded'->>'snr' IS NOT NULL")
    norm_line = week_norm_note(float(y_snr) if y_snr is not None else None,
                               float(w_norm) if w_norm is not None else None)

    import datetime as _dt
    lines = [f"☕ MeshGate бриф · {_dt.date.today():%d.%m.%Y} (посл. 24 ч)"]
    lines.append(f"пакети: {total or 0} · възли: {mesh_nodes or 0} активни,"
                 f" {new_nodes or 0} нови")
    if top_ch:
        lines.append("канали: " + ", ".join(
            f"{r['ch']} ({r['n']})" for r in top_ch if r['ch']))
    if quiet:
        lines.append("👀 тихи фаворити (активни вчера, мълчат >12 ч): "
                     + ", ".join(r["external_id"] for r in quiet))
    if low_bat:
        items = [f"{r['node']} {float(r['bat']):.0f}%" for r in low_bat[:3]]
        total_low = int(low_bat[0]["total"]) if low_bat else 0
        if total_low > 3:
            items.append(f"+{total_low - 3} още")
        lines.append("🔋 слаби батерии: " + " ".join(items))
    if dead:
        lines.append(f"🚫 мъртви букви: {dead}"
                     " (търси „deadletter/“ в Packet Explorer)")
    if sent_notifs:
        lines.append(f"известия изпратени: {sent_notifs}")
    if norm_line:
        lines.append(f"📡 {norm_line}")
    if not low_bat and not dead:
        lines.append("всичко е спокойно — нито слаби батерии, нито мъртви букви.")
    return "\n".join(lines)


def _parse_hhmm(s: str) -> tuple[int, int] | None:
    try:
        h, m = str(s).strip().split(":")
        hh, mm = int(h), int(m)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    return None


def in_quiet_hours(cfg: dict, now=None) -> bool:
    """Тихи часове per канал: {"quiet_hours": {"start": "23:00", "end": "07:00"}}.
    Обхождат полунощ; при невалиден формат — не са активни (безчувствено)."""
    qh = (cfg or {}).get("quiet_hours") or {}
    start, end = _parse_hhmm(qh.get("start", "")), _parse_hhmm(qh.get("end", ""))
    if not start or not end:
        return False
    t = now or time.localtime()
    minutes = t.tm_hour * 60 + t.tm_min
    s, e = start[0] * 60 + start[1], end[0] * 60 + end[1]
    if s <= e:
        return s <= minutes < e
    return minutes >= s or minutes < e  # през полунощ


def render_message(topic: str, decoded: dict | None, origin: str,
                   template: str | None = None) -> str:
    """Човешко съобщение от пакет: тема + най-смисленото от декодирания блок.

    Със собствен шаблон (per канал) се заместват {topic} {channel}
    {severity} {node} {text} {battery} {snr} {rssi} {lat} {lng} {origin};
    неизвестните placeholders остават като текст, липсващите стойности
    са „—“."""
    d = decoded or {}
    if template:
        vals = {
            "topic": topic,
            "channel": d.get("channel") or "—",
            "severity": d.get("severity") or "info",
            "node": d.get("node") or "—",
            "text": d.get("text") or "—",
            "battery": (f"{round(d['battery'])}%"
                        if isinstance(d.get("battery"), (int, float)) else "—"),
            "snr": (f"{round(d['snr'], 1)} dB"
                    if isinstance(d.get("snr"), (int, float)) else "—"),
            "rssi": (str(d["rssi"])
                     if isinstance(d.get("rssi"), (int, float)) else "—"),
            "lat": (f"{d['lat']:.5f}" if isinstance(d.get("lat"), (int, float)) else "—"),
            "lng": (f"{d['lng']:.5f}" if isinstance(d.get("lng"), (int, float)) else "—"),
            "origin": origin,
        }
        out = str(template)
        for key, val in vals.items():
            out = out.replace("{" + key + "}", str(val))
        return out
    lines = [f"MeshGate · {topic}"]
    if d.get("text"):
        lines.append(str(d["text"]))
    parts = []
    if d.get("node"):
        parts.append(f"възел {d['node']}")
    if d.get("channel"):
        parts.append(f"канал {d['channel']}")
    if isinstance(d.get("battery"), (int, float)):
        parts.append(f"батерия {round(d['battery'])}%")
    if isinstance(d.get("lat"), (int, float)) and isinstance(d.get("lng"), (int, float)):
        parts.append(f"позиция {d['lat']}, {d['lng']}")
    if isinstance(d.get("snr"), (int, float)):
        parts.append(f"SNR {round(d['snr'], 1)}")
    if parts:
        lines.append(" · ".join(str(p) for p in parts))
    if origin.startswith("bridge:"):
        lines.append(f"via {origin}")
    return "\n".join(lines)


class NotificationEngine:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.channels: dict[str, dict] = {}
        self._queue: asyncio.Queue[tuple[str, dict | None, str]] = asyncio.Queue(QUEUE_MAX)
        self._stop = asyncio.Event()
        self._worker: asyncio.Task | None = None
        # канал → последно изпращане (анти-спам) и дедуп ключове
        self._last_sent: dict[str, float] = {}
        self._seen: dict[str, float] = {}
        self._client = httpx.AsyncClient(timeout=SEND_TIMEOUT_S)

    # --- жизнен цикъл -------------------------------------------------------

    async def load(self) -> None:
        rows = await self.pool.fetch(
            "SELECT id, name, kind, topic_pattern, config, template,"
            " severity, min_interval_s, enabled"
            " FROM notification_channels WHERE enabled"
        )
        channels: dict[str, dict] = {}
        for r in rows:
            ch = dict(r)
            cfg = ch["config"]
            if isinstance(cfg, str):  # asyncpg връща jsonb като текст
                cfg = json.loads(cfg)
            ch["config"] = cfg or {}
            channels[str(ch["id"])] = ch
        self.channels = channels
        log.info("известия: заредени %d активни канала", len(self.channels))

    def start(self) -> None:
        self._worker = asyncio.create_task(self._run(), name="notify")
        self._digest_task = asyncio.create_task(self._digest_loop(), name="notify-digest")

    async def stop(self) -> None:
        self._stop.set()
        for t in (self._worker, getattr(self, "_digest_task", None)):
            if t:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        await self._client.aclose()

    # --- сутрешен бриф (docs/15 Вълна 1) ------------------------------------

    async def _digest_tick(self, now) -> None:
        """Едно минутно измерване на бриф цикъла (тестируемо без event loop):
        за всеки канал с config.digest_hour == текущия час — ЕДНО съобщение
        на ден; рестартът е предпазен чрез журнала; боклучивият час на един
        канал не спира другите; денят се маркира САМО след успешен send;
        повреден канал има максимум MAX_DIGEST_TRIES опита за деня."""
        last_sent_day = self._digest_sent
        tries = self._digest_tries
        today = time.strftime("%Y-%m-%d", now)
        due: list[dict] = []
        for ch in list(self.channels.values()):
            cid = str(ch["id"])
            try:
                hour = int((ch.get("config") or {}).get("digest_hour"))
            except (TypeError, ValueError):
                continue  # боклучив config на ЕДИН канал не спира другите
            if not 0 <= hour <= 23 or hour != now.tm_hour:
                continue
            if last_sent_day.get(cid) == today:
                continue
            if tries.get(cid, (0, ""))[1] == today and tries[cid][0] >= MAX_DIGEST_TRIES:
                continue  # изчерпа опитите за днес — без spam
            # рестарт в час X не праща втори бриф: журналът е истина
            already = await self.pool.fetchval(
                "SELECT count(*) FROM notification_log"
                " WHERE channel_id=$1 AND topic='meshgate/digest'"
                "   AND status='sent' AND ts::date = current_date",
                ch["id"],
            )
            if already:
                last_sent_day[cid] = today
                continue
            due.append(ch)
        if not due:
            return
        text = await build_digest(self.pool)  # веднъж за всички канали
        for ch in due:
            cid = str(ch["id"])
            try:
                await self._send(ch, "meshgate/digest", text)
            except Exception as exc:
                reason = str(exc)[:300] or type(exc).__name__  # timeout-ите дават празен str
                n_today = (tries.get(cid, (0, today))[0] + 1
                           if tries.get(cid, (0, ""))[1] == today else 1)
                tries[cid] = (n_today, today)
                await self._log(ch, "meshgate/digest", text, "failed", reason)
                continue  # денят НЕ се маркира — следващият tick опитва
            last_sent_day[cid] = today
            await self._log(ch, "meshgate/digest", text, "sent", None)

    async def _digest_loop(self) -> None:
        self._digest_sent: dict[str, str] = getattr(self, "_digest_sent", {})
        self._digest_tries: dict[str, tuple[int, str]] = getattr(
            self, "_digest_tries", {})
        while not self._stop.is_set():
            try:
                await self._digest_tick(time.localtime())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("известия: грешка в бриф цикъла")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=DIGEST_TICK_S)
            except asyncio.TimeoutError:
                pass

    # --- входна точка (викана от ingest, неблокиращо) -----------------------

    def handle_local(self, topic: str, decoded: dict | None, origin: str) -> None:
        if not self.channels:
            return
        try:
            self._queue.put_nowait((topic, decoded, origin))
        except asyncio.QueueFull:
            log.warning("известия: опашката е пълна — съобщение за %r се пропуска", topic)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                topic, decoded, origin = await self._queue.get()
                await self._dispatch(topic, decoded, origin)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("известия: грешка в работника")

    # --- вътрешности ---------------------------------------------------------

    async def _dispatch(self, topic: str, decoded: dict | None, origin: str) -> None:
        for ch in list(self.channels.values()):
            if not mqtt_match(ch["topic_pattern"], topic):
                continue
            message = render_message(topic, decoded, origin, ch.get("template"))
            # ниво на важност: съобщението носи severity (от decoded payload —
            # правилата могат да го сложат с transform set_fields); каналът
            # има праг. Под прага → пропуск; в тихите часове → само critical.
            d = decoded or {}
            sev = str(d.get("severity") or "info")
            if SEVERITY_RANK.get(sev, 0) < SEVERITY_RANK.get(ch.get("severity") or "info", 0):
                await self._log(ch, topic, message, "skipped",
                                f"под нивото на канала ({sev} < {ch.get('severity')})")
                continue
            if sev != "critical" and in_quiet_hours(ch["config"] or {}):
                await self._log(ch, topic, message, "skipped", "тихи часове")
                continue
            key = f"{ch['id']}|{topic}|{message}"
            now = time.monotonic()
            self._evict(now)
            if self._seen.get(key, 0) > now:
                await self._log(ch, topic, message, "skipped", "дубликат в рамките на минута")
                continue
            last = self._last_sent.get(ch["id"], 0)
            if now - last < ch["min_interval_s"]:
                await self._log(ch, topic, message, "skipped",
                                f"анти-спам: мин. интервал {ch['min_interval_s']}s")
                continue
            self._seen[key] = now + DEDUPE_TTL_S
            self._last_sent[ch["id"]] = now
            try:
                await self._send(ch, topic, message)
                await self._log(ch, topic, message, "sent", None)
            except Exception as exc:  # провален канал не спира останалите
                reason = str(exc)[:300] or type(exc).__name__  # timeout-ите дават празен str
                await self._log(ch, topic, message, "failed", reason)

    def _evict(self, now: float) -> None:
        if len(self._seen) < 4096:
            return
        for k in [k for k, exp in self._seen.items() if exp <= now]:
            del self._seen[k]

    async def _send(self, ch: dict, topic: str, message: str) -> None:
        cfg = ch["config"] or {}
        kind = ch["kind"]
        if kind == "telegram":
            token = str(cfg.get("bot_token") or "")
            chat = str(cfg.get("chat_id") or "")
            if not token or not chat:
                raise ValueError("липсват bot_token/chat_id в конфигурацията")
            r = await self._client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": message},
            )
            r.raise_for_status()
        elif kind == "email":
            to = str(cfg.get("to") or "")
            if not to:
                raise ValueError("липсва получател (to) в конфигурацията")
            s = settings()
            host = getattr(s, "smtp_host", "") or ""
            if not host:
                raise ValueError("SMTP не е конфигуриран (MESHGATE_SMTP_HOST)")
            msg = EmailMessage()
            msg["Subject"] = f"MeshGate: {topic}"
            msg["From"] = getattr(s, "smtp_from", "") or "meshgate@localhost"
            msg["To"] = to
            msg.set_content(message)

            def _smtp() -> None:
                port = int(getattr(s, "smtp_port", 587) or 587)
                with smtplib.SMTP(host, port, timeout=SEND_TIMEOUT_S) as srv:
                    user = getattr(s, "smtp_user", "") or ""
                    password = getattr(s, "smtp_password", "") or ""
                    if user:
                        srv.starttls()
                        srv.login(user, password)
                    srv.send_message(msg)

            await asyncio.to_thread(_smtp)
        elif kind == "webhook":
            url = str(cfg.get("url") or "")
            if not url:
                raise ValueError("липсва url в конфигурацията")
            r = await self._client.post(url, json={
                "topic": topic, "message": message, "source": "meshgate",
            })
            r.raise_for_status()
        elif kind == "whatsapp":
            # CallMeBot (както в NetSight): праща на личен номер с безплатен
            # apikey от https://www.callmebot.com/ — Business API върви през
            # webhook канала
            phone = str(cfg.get("phone") or "").replace("+", "")
            apikey = str(cfg.get("apikey") or "")
            if not phone or not apikey:
                raise ValueError("липсват phone/apikey (CallMeBot)")
            r = await self._client.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": phone, "apikey": apikey, "text": message},
            )
            r.raise_for_status()
        else:
            raise ValueError(f"непознат вид канал {kind!r}")

    async def _log(self, ch: dict, topic: str, message: str, status: str,
                   error: str | None) -> None:
        try:
            await self.pool.execute(
                "INSERT INTO notification_log (channel_id, topic, message, status, error)"
                " VALUES ($1,$2,$3,$4,$5)",
                ch["id"], topic, message[:2000], status, error,
            )
        except Exception:
            log.exception("известия: не се записа в журнала")

    async def send_test(self, ch: dict) -> None:
        """Бутон „Тест“ в UI — директно изпращане без мачване/лимити."""
        await self._send(ch, "meshgate/test", "Тестово известие от MeshGate ✓")

    def counters(self) -> dict:
        return {
            "channels": len(self.channels),
            "queued": self._queue.qsize(),
        }


def fingerprint(topic: str, message: str) -> str:
    return hashlib.sha256(f"{topic}|{message}".encode()).hexdigest()[:16]


def config_public(cfg: dict) -> dict:
    """Конфиг за API отговори — скрива тайните (bot_token/apikey)."""
    out = dict(cfg or {})
    if out.get("bot_token"):
        out["bot_token"] = "***"
    if out.get("apikey"):
        out["apikey"] = "***"
    return out


def config_valid(kind: str, cfg: dict) -> tuple[bool, str]:
    cfg = cfg or {}
    # бриф часът е общ за всички видове канали (ако съществува);
    # bool е subclass на int в Python — True не е валиден час
    dh = cfg.get("digest_hour")
    if dh is not None and (isinstance(dh, bool)
                           or not isinstance(dh, int)
                           or not 0 <= dh <= 23):
        return False, "digest_hour трябва да е цяло число 0–23"
    if kind == "telegram":
        if not cfg.get("bot_token") or not cfg.get("chat_id"):
            return False, "telegram изисква bot_token и chat_id"
    elif kind == "email":
        if not cfg.get("to") or "@" not in str(cfg.get("to")):
            return False, "email изисква валиден получател (to)"
    elif kind == "webhook":
        url = str(cfg.get("url") or "")
        if not url.startswith(("http://", "https://")):
            return False, "webhook изисква http(s) url"
    elif kind == "whatsapp":
        phone = str(cfg.get("phone") or "")
        if not phone or not phone.lstrip("+").isdigit():
            return False, "whatsapp (CallMeBot) изисква phone (само цифри) и apikey"
        if not cfg.get("apikey"):
            return False, "whatsapp (CallMeBot) изисква apikey (от callmebot.com)"
    else:
        return False, f"непознат вид канал {kind!r}"
    return True, ""
