"""Ingestion: wildcard subscriber към EMQX -> packets/events/devices + live bus."""

import asyncio
import hashlib
import json
import logging
import time

import aiomqtt
import asyncpg

from ..bus import bus
from ..bridge.engine import BridgeEngine
from ..bridge.rules import DedupeCache
from ..config import settings
from .mesh_decode import decode_envelope_protobuf, envelope_info, is_meshtastic_topic, topic_parts

log = logging.getLogger("meshgate.ingest")

RECONNECT_MIN = 1.0
RECONNECT_MAX = 30.0


def decode_generic(payload: bytes) -> dict:
    """Общ декодер: JSON / текст / бинарно. Грешка в декодирането не хвърля —
    връща статус + причина, суровият payload се пази."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "packet_type": "binary",
            "payload_text": None,
            "decoder_id": None,
            "decode_status": "not_attempted",
            "decode_error": "binary payload: няма регистриран декодер",
        }
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            data = json.loads(text)
            return {
                "packet_type": "json",
                "payload_text": text,
                "decoder_id": "generic-json",
                "decode_status": "decoded",
                "decode_error": None,
                "decoded": data,
            }
        except json.JSONDecodeError as exc:
            return {
                "packet_type": "text",
                "payload_text": text,
                "decoder_id": "generic-text",
                "decode_status": "partial",
                "decode_error": f"прилича на JSON, но не се парсва: {exc}",
            }
    return {
        "packet_type": "text",
        "payload_text": text,
        "decoder_id": "generic-text",
        "decode_status": "decoded",
        "decode_error": None,
    }


class IngestService:
    def __init__(self, pool: asyncpg.Pool, bridge: BridgeEngine):
        self.pool = pool
        self.bridge = bridge
        self.psk_map: dict[str, bytes] = {}  # Т36: channel_id → expand-нат ключ
        self.routing = None  # RoutingEngine — свързва се в main.py
        self.notify = None   # NotificationEngine — свързва се в main.py
        self.ha = None       # HomeAssistantEngine — свързва се в main.py
        self.healthy = False
        self.last_message_at: float | None = None
        # дедупликация по Meshtastic packet id (docs/10 3b): едно и също
        # съобщение, донесено от два моста/брокера, се обработва веднъж
        self._mesh_seen = DedupeCache(ttl_s=180.0, max_size=16384)
        self.mesh_deduped = 0
        self.muted_dropped = 0
        self._client = None
        self._stop = asyncio.Event()

    def mesh_duplicate(self, origin: str, mesh: dict | None) -> bool:
        """True → пропускаме пакета: същият (възел, packet id) вече мина.

        Важи само за чисти входящи публикации (local) и копията от входящите
        мостове (bridge:*) — там повторът е истинско дубликат от mesh мрежата.
        Препращанията на собствените правила (routing:*) са легитимни нови
        публикации и НЕ се режат."""
        if not mesh or not mesh.get("packet_id"):
            return False
        if origin.startswith("routing:"):
            return False
        node = mesh.get("node_id") or "?"
        key = f"msh-pkt:{node}:{mesh['packet_id']}"
        if self._mesh_seen.seen_recently(key):
            self.mesh_deduped += 1
            return True
        self._mesh_seen.add(key)
        return False

    async def load_psk_map(self, psk_cfg: dict | None = None) -> None:
        """Т36 срез 2 (ADR-007): ключовете на каналите от settings ('psk' —
        JSON {канал: base64}). 1-байтови PSK (AQ== и пр.) се разширяват
        тук; грешните записи се прескачат тихо (partial остава честен).
        Живо обновяване: PUT /v1/system/psk вика това без рестарт."""
        import base64 as _b64
        from .mesh_decode import expand_psk
        if psk_cfg is None:
            row = await self.pool.fetchrow("SELECT value FROM settings WHERE key='psk'")
            if row is None:
                self.psk_map = {}
                return
            try:
                psk_cfg = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
            except (json.JSONDecodeError, TypeError):
                psk_cfg = {}
        out: dict[str, bytes] = {}
        for ch, b64 in (psk_cfg or {}).items():
            if not isinstance(b64, str) or not b64:
                continue
            try:
                key = expand_psk(_b64.b64decode(b64))
                if key:
                    out[ch] = key
            except Exception:
                continue  # лош запис — без ключ за този канал
        self.psk_map = out
        log.info("psk: заредени ключове за %d канала", len(out))

    async def run(self) -> None:
        s = settings()
        backoff = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=s.emqx_host,
                    port=1883,
                    username=s.emqx_ingest_user,
                    password=s.emqx_ingest_password,
                    identifier="meshgate-ingest",
                    # MQTT 5: нужни са ни user properties (origin marker за цикли)
                    protocol=aiomqtt.ProtocolVersion.V5,
                ) as client:
                    self._client = client
                    await client.subscribe("#")
                    self.healthy = True
                    backoff = RECONNECT_MIN
                    log.info("ingest: свързан с брокера")
                    async for message in client.messages:
                        self.last_message_at = time.monotonic()
                        try:
                            await self._handle(client, message)
                        except Exception:
                            log.exception("ingest: грешка при обработка на пакет")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.healthy = False
                self._client = None
                log.warning("ingest: връзката падна (%s), нов опит след %.1fs", exc, backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, RECONNECT_MAX)
            finally:
                self._client = None

    async def _handle(self, client, message) -> None:
        topic = str(message.topic)
        payload: bytes = bytes(message.payload)
        # homeassistant/ discovery темите са чиста интеграционна водопроводия —
        # висок churn, нулева стойност за журнала; не се записват изобщо
        if topic.startswith("homeassistant/"):
            return
        decoded = decode_generic(payload)

        origin = "local"
        props = getattr(message, "properties", None)
        # paho Properties пази свойствата в .UserProperty (списък от кортежи)
        user_props = getattr(props, "UserProperty", None) or []
        for key, val in user_props:
            if key == "mg_origin":
                origin = val
                break

        # RETAINED преиграване на собствените ни изходи (deadletter/…,
        # alerts/…): брокерът връща пазените retain съобщения на ВЕЧЕН
        # абонат при повторно свързване — живата доставка вече ги записа,
        # преигравката е дубликат (retain=1 е само при replay; живите
        # доставки идват с retain=0 дори публикувани с retain=True).
        # Установено на живо: всеки рестарт на api дублира мъртвите букви.
        if getattr(message, "retain", False) and origin.startswith("routing:"):
            return

        # Meshtastic разпознаване (docs/10): устройство = възелът (!hex), не темата
        mesh = None
        parts = None  # topic_parts само за msh теми (Т37: по-долу ползва None-guard)
        if is_meshtastic_topic(topic):
            # JSON envelope първо; ако payload-ът е бинарен protobuf — 3b
            # декодерът вади тип/източник/текст/батерия/позиция/SNR/RSSI
            mesh = envelope_info(decoded.get("payload_text") or "")
            if mesh is None:
                mesh = decode_envelope_protobuf(payload, self.psk_map)
            # Т15 П3: чутост-запис ПРЕДИ дедупа — дедуп ключът е (възел,
            # packet_id) и реже копието от ДРУГИ гейт; „кой чу" е точно
            # това. Всяко ухо = (packet_id, gateway_id); повторенията на
            # същото ухо броят copies. Без гейт в envelope — без запис.
            gw_ear = (mesh or {}).get("gateway_id")
            if mesh and mesh.get("packet_id") and gw_ear and not origin.startswith("routing:"):
                try:
                    await self.pool.execute(
                        "INSERT INTO packet_heard (packet_id, gateway_id)"
                        " VALUES ($1, $2)"
                        " ON CONFLICT (packet_id, gateway_id) DO UPDATE SET"
                        "  last_ts = now(), copies = packet_heard.copies + 1",
                        mesh["packet_id"], gw_ear)
                except Exception:
                    log.exception("packet_heard: записът пропадна (не спира ingest)")
            if self.mesh_duplicate(origin, mesh):
                log.debug("ingest: дедупликация по packet id (%s)", mesh.get("packet_id"))
                return
            parts = topic_parts(topic)
            device_key = parts["node"] or topic
            device_proto = "meshtastic"
            if mesh:
                decoded["packet_type"] = mesh["packet_type"]
                decoded["decoder_id"] = mesh["decoder_id"]
                decoded["decode_status"] = mesh["decode_status"]
                decoded["decode_error"] = mesh["decode_error"]
                decoded["decoded"] = {
                    **(decoded.get("decoded") or {}),
                    "text": mesh["text"],
                    "battery": mesh["battery"],
                    "lat": mesh["lat"],
                    "lng": mesh["lng"],
                    "channel": parts["channel"] or mesh.get("channel_id"),
                    "node": mesh["node_id"] or parts["node"],
                    "packet_id": mesh.get("packet_id"),
                    "snr": mesh.get("snr"),
                    "rssi": mesh.get("rssi"),
                    "neighbors": mesh.get("neighbors"),
                    "route": mesh.get("route"),
                    "user": mesh.get("user"),
                    "ack_request_id": mesh.get("ack_request_id"),
                    "ack_error_reason": mesh.get("ack_error_reason"),
                }
        else:
            device_key = topic
            device_proto = "mqtt"

        # заглушени/блокирани възли (по желание на собственика): пакетите им
        # не се записват, не рутират и не известяват — само се броят
        flags = await self.pool.fetchrow(
            "SELECT muted, blocked FROM devices"
            " WHERE protocol = $1 AND external_id = $2",
            device_proto, device_key,
        )
        if flags is not None and (flags["muted"] or flags["blocked"]):
            self.muted_dropped += 1
            return

        # платформените ИЗХОДНИ теми (meshgate/… на HA адаптера) не са
        # устройства-сензори — записваме пакета за преглед, без device ред
        is_platform_output = topic.startswith(("meshgate/", "deadletter/"))

        # PG text/jsonb отхвърля NUL ("\u0000"); бинарните protobuf
        # payload-и понякога декодират до такива низове — чистим НА МЯСТО
        # всички текстове; суровите байтове остават в payload_raw
        _strip_nuls(decoded)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if not is_platform_output:
                    device_id = await conn.fetchval(
                        "INSERT INTO devices (protocol, external_id, name, last_seen_at, status)"
                        " VALUES ($1, $2, $2, now(), 'online')"
                        " ON CONFLICT (protocol, external_id)"
                        " DO UPDATE SET last_seen_at = now(), status = 'online'"
                        " RETURNING id",
                        device_proto,
                        device_key,
                    )
                else:
                    device_id = await conn.fetchval(
                        "SELECT id FROM devices WHERE protocol = $1 AND external_id = $2",
                        "platform", "meshgate-output",
                    )
                    if device_id is None:
                        device_id = await conn.fetchval(
                            "INSERT INTO devices (protocol, external_id, name, status)"
                            " VALUES ('platform', 'meshgate-output', 'платформени изходи', 'online')"
                            " ON CONFLICT (protocol, external_id) DO NOTHING RETURNING id",
                        )
                # PostgreSQL text/jsonb не приемат NUL байтове; бинарните
                # protobuf payload-и понякога ги вадят като текст —
                # _strip_nuls ги е махнал още на входа; суровият байт
                # остава в payload_raw
                # Т36: NODEINFO с decoded User → учим името на възела ВЕДНЪЖ;
                # COALESCE пази старото име ако новият пакет е по-беден
                # Т37: кой реален MQTT гейт излъча пакета и в кой канал —
                # кръстосаната референция гейтове×канали (без routing:* изходи
                # и платформени теми — те са платформа, не гейтове).
                # gateway_id е в mesh (envelope), каналът — от темата.
                gw = (mesh or {}).get("gateway_id")
                if not gw and not is_platform_output:
                    ch0 = topic.split('/')
                    gw = f"{ch0[0]}/{ch0[1]}" if len(ch0) > 1 else topic
                if gw and not is_platform_output:
                    ch = (parts.get("channel") if parts else None) or                         "_other"
                    await conn.execute(
                        "INSERT INTO gateway_channels (gateway_id, channel, packets)"
                        " VALUES ($1,$2,1)"
                        " ON CONFLICT (gateway_id, channel) DO UPDATE SET"
                        "  packets = gateway_channels.packets + 1, last_ts = now()",
                        gw, ch)
                    await conn.execute(
                        "INSERT INTO gateways (gateway_id, kind)"
                        " VALUES ($1, CASE WHEN $1 LIKE 'bridge:%' THEN 'bridge' ELSE 'mqtt' END)"
                        " ON CONFLICT (gateway_id) DO UPDATE SET last_heard = now()",
                        gw)
                u = (decoded.get("decoded") or {}).get("user")
                if u and device_proto == "meshtastic" and device_key:
                    prev = await conn.fetchrow(
                        "SELECT long_name, short_name, pubkey_fp FROM node_registry"
                        " WHERE node_id = $1", device_key.lower())
                    await conn.execute(
                        "INSERT INTO node_registry (node_id, long_name, short_name,"
                        " hw_model, role, pubkey_fp)"
                        " VALUES ($1,$2,$3,$4,$5,$6)"
                        " ON CONFLICT (node_id) DO UPDATE SET"
                        "  long_name = COALESCE(EXCLUDED.long_name, node_registry.long_name),"
                        "  short_name = COALESCE(EXCLUDED.short_name, node_registry.short_name),"
                        "  hw_model = COALESCE(EXCLUDED.hw_model, node_registry.hw_model),"
                        "  role = COALESCE(EXCLUDED.role, node_registry.role),"
                        "  pubkey_fp = COALESCE(EXCLUDED.pubkey_fp, node_registry.pubkey_fp),"
                        "  last_heard = now(), updated_at = now()",
                        device_key.lower(),
                        u.get("long_name"), u.get("short_name"),
                        u.get("hw_model"), u.get("role"), u.get("pubkey_fp"))
                    # Т36 срез 2: история на преименуванията — при СМЯНА на името
                    # затваряме предишния период и отваряме нов
                    new_l, new_s = (u.get("long_name"), u.get("short_name"))
                    if prev and (prev["long_name"], prev["short_name"]) != (new_l, new_s)                             and (prev["long_name"] or prev["short_name"]):
                        await conn.execute(
                            "UPDATE node_names_history SET valid_to = now()"
                            " WHERE node_id = $1 AND valid_to IS NULL", device_key.lower())
                        await conn.execute(
                            "INSERT INTO node_names_history"
                            " (node_id, long_name, short_name, pubkey_fp, valid_from)"
                            " VALUES ($1,$2,$3,$4,"
                            "  (SELECT COALESCE(max(valid_to), now()) FROM node_names_history"
                            "   WHERE node_id = $1))",
                            device_key.lower(), prev["long_name"], prev["short_name"],
                            prev["pubkey_fp"])
                packet_id = await conn.fetchval(
                    "INSERT INTO packets (topic, packet_type, payload_raw, payload_text,"
                    " payload_size, decode_status, decode_error, decoder_id, origin)"
                    " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id",
                    topic,
                    decoded["packet_type"],
                    payload,
                    decoded.get("payload_text"),
                    len(payload),
                    decoded["decode_status"],
                    decoded.get("decode_error"),
                    decoded.get("decoder_id"),
                    origin,
                )
                await conn.execute(
                    "INSERT INTO events (device_id, packet_id, source, event_type, payload)"
                    " VALUES ($1,$2,'generic-mqtt',$3,$4::jsonb)",
                    device_id,
                    packet_id,
                    decoded["packet_type"],
                    json.dumps(
                        {
                            "text": decoded.get("payload_text"),
                            "decoded": decoded.get("decoded"),
                            "size": len(payload),
                        }
                    ),
                )

        bus.publish(
            {
                "type": "packet",
                "data": {
                    "id": str(packet_id),
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "topic": topic,
                    "packet_type": decoded["packet_type"],
                    "decode_status": decoded["decode_status"],
                    "payload_size": len(payload),
                    "origin": origin,
                },
            }
        )

        await self.bridge.handle_local(topic, payload, decoded["packet_type"], origin)
        if self.routing is not None:
            await self.routing.handle_local(
                topic, payload, decoded.get("decoded"), origin
            )
        if self.notify is not None:
            # неблокиращо: engine-ът си има опашка и работник
            self.notify.handle_local(topic, decoded.get("decoded"), origin)
        if self.ha is not None:
            # неблокиращо: HA адаптерът също има опашка
            self.ha.handle_local(topic, decoded.get("decoded"), origin)

    async def publish_local(
        self, topic: str, payload: bytes, origin_marker: str, qos: int = 0, retain: bool = False
    ) -> None:
        """Публикуване в локалния брокер от името на платформата (routing
        дестинации) — с origin marker, за да не се зацикля обработката."""
        from paho.mqtt.packettypes import PacketTypes
        from paho.mqtt.properties import Properties as PahoProps

        if self._client is None:
            raise RuntimeError("ingest: няма връзка с брокера")
        props = PahoProps(PacketTypes.PUBLISH)
        props.UserProperty = [("mg_origin", origin_marker)]
        await self._client.publish(
            topic, payload=payload, qos=qos, retain=retain, properties=props
        )

    def stop(self) -> None:
        self._stop.set()


def payload_fingerprint(topic: str, payload: bytes) -> str:
    return hashlib.sha256(f"{topic}|".encode() + payload).hexdigest()


def _strip_nuls(obj) -> None:
    """Маха NUL байтове от всички низове в decoded речника (на място).

    PostgreSQL text/jsonb отхвърля NUL (0x00 / "\u0000") — редки binaries
    от реалния mesh трафик го раждат като текст. Ключовете на речниците
    не се пипат (низ-ключ с NUL не се среща; стойностите — да)."""
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if isinstance(v, str) and "\x00" in v:
                obj[k] = v.replace("\x00", "")
            else:
                _strip_nuls(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and "\x00" in v:
                obj[i] = v.replace("\x00", "")
            else:
                _strip_nuls(v)
