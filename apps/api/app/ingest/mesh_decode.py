"""Разпознаване на Meshtastic по MQTT (docs/10-meshtastic-mqtt.md, фаза 3a/3b).

Чисти функции без I/O: детектор по тема + два декодера на ServiceEnvelope —
JSON (плоският firmware формат и вложеният proto3-JSON) и бинарен protobuf
(минимален wire парсер, ADR-005). Поддържа snake_case / camelCase имена.
Неизвестните структури остават честно „binary / not_attempted“."""

import base64
import hashlib
import json

MESHTASTIC_PREFIX = "msh/"

# portnum → наш packet_type (записва се в packets.packet_type и се вижда в UI)
PORTNUM_TYPES = {
    "TEXT_MESSAGE_APP": "meshtastic-text",
    "TEXT_MESSAGE_COMPRESSED_APP": "meshtastic-text",
    "TELEMETRY_APP": "meshtastic-telemetry",
    "POSITION_APP": "meshtastic-position",
    "NODEINFO_APP": "meshtastic-nodeinfo",
    "MAP_REPORT_APP": "meshtastic-map",
    "ROUTING_APP": "meshtastic-routing",
    "NEIGHBORINFO_APP": "meshtastic-neighbor",
    "TRACEROUTE_APP": "meshtastic-traceroute",
    "WAYPOINT_APP": "meshtastic-waypoint",
    "PAXCOUNTER_APP": "meshtastic-paxcounter",
}


def is_meshtastic_topic(topic: str) -> bool:
    return topic.startswith(MESHTASTIC_PREFIX)


def topic_parts(topic: str) -> dict:
    """msh/<region>/2/e|c|json/<channel>/!<nodehex> → регион/канал/възел."""
    toks = topic.split("/")
    node = next((t for t in toks if t.startswith("!")), None)
    channel = None
    for i, t in enumerate(toks):
        if t in ("e", "c", "json") and i + 1 < len(toks) and not toks[i + 1].startswith("!"):
            channel = toks[i + 1]
            break
    return {"region": toks[1] if len(toks) > 1 else None, "channel": channel, "node": node}


def _get(doc, *paths):
    """Връща първото съществуващо поле по точен path — за snake/camel варианти."""
    for p in paths:
        cur = doc
        ok = True
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return None


def _b64_text(value: str) -> str | None:
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except Exception:
        return None


def envelope_info(payload_text: str) -> dict | None:
    """JSON ServiceEnvelope → разпозната информация или None (не е JSON envelope).

    Поддържа плоския формат на firmware-а (sender/decoded на top level) и
    вложения proto3-JSON (packet.decoded). Връща: packet_type, text, battery,
    lat/lng (градуси), node_id, packet_id, snr/rssi, канал/gateway, decode_status,
    decode_error, decoder_id."""
    try:
        doc = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(doc, dict):
        return None
    # вложен proto3-JSON: {packet:{from,id,rx_snr,decoded{...}}, channel_id, gateway_id}
    pkt = doc.get("packet") if isinstance(doc.get("packet"), dict) else doc
    decoded = pkt.get("decoded") if isinstance(pkt.get("decoded"), dict) else {}
    portnum = str(
        decoded.get("portnum") or doc.get("type") or ""
    ).upper()
    ptype = PORTNUM_TYPES.get(portnum)
    out = {
        "packet_type": ptype or (f"meshtastic-{portnum.lower()}" if portnum else None),
        "text": None,
        "battery": None,
        "lat": None,
        "lng": None,
        "node_id": None,
        "decode_status": "decoded",
        "decode_error": None,
        "decoder_id": "meshtastic-json",
        "packet_id": None,
        "snr": None,
        "rssi": None,
        "channel_id": doc.get("channel_id"),
        "gateway_id": doc.get("gateway_id"),
        "broadcast": None,
    }
    if isinstance(pkt.get("id"), int) and pkt["id"] > 0:
        out["packet_id"] = pkt["id"]
    for snr_key in ("rx_snr", "snr"):
        if isinstance(pkt.get(snr_key), (int, float)):
            out["snr"] = float(pkt[snr_key])
            break
    for rssi_key in ("rx_rssi", "rssi"):
        if isinstance(pkt.get(rssi_key), int):
            out["rssi"] = pkt[rssi_key]
            break
    to = pkt.get("to")
    out["broadcast"] = to in (0xFFFFFFFF, -1)

    node = _get(doc, "nodeId", "node_id", "sender") or (
        pkt.get("nodeId") if pkt is not doc else None
    )
    if isinstance(node, str) and node:
        out["node_id"] = node
    elif isinstance(pkt.get("from"), int):
        out["node_id"] = f"!{pkt['from']:08x}"

    if portnum.startswith("TEXT_MESSAGE"):
        text = decoded.get("text")
        if not isinstance(text, str) and isinstance(decoded.get("payload"), str):
            text = _b64_text(decoded["payload"])
        if isinstance(text, str):
            out["text"] = text
        else:
            out["decode_status"] = "partial"
            out["decode_error"] = "текстовото payload не е нито чисто, нито base64"

    if portnum == "TELEMETRY_APP":
        battery = _get(
            decoded,
            "telemetry.device_metrics.battery_level",
            "telemetry.deviceMetrics.batteryLevel",
        )
        if isinstance(battery, (int, float)):
            out["battery"] = battery
        else:
            out["decode_status"] = "partial"
            out["decode_error"] = "телеметрия без device_metrics (възможно е батар. модул)"

    for src in ("position", "map_report", "mapReport"):
        lat_i = _get(decoded, f"{src}.latitude_i", f"{src}.latitudeI")
        lng_i = _get(decoded, f"{src}.longitude_i", f"{src}.longitudeI")
        if isinstance(lat_i, (int, float)) and isinstance(lng_i, (int, float)):
            out["lat"] = round(lat_i / 1e7, 6)
            out["lng"] = round(lng_i / 1e7, 6)
            break

    if portnum in ("NODEINFO_APP", "MAP_REPORT_APP"):
        # Т36: User protobuf-ът идва като base64 в decoded.payload (JSON
        # пликовете от публичните брокери) или готови полета user.*  —
        # без това регистърът на имената остава празен при JSON трафик.
        u = None
        for path in ("user.longName", "user.long_name"), ("user.shortName", "user.short_name"):
            v = _get(decoded, *path)
            if isinstance(v, str) and v.strip():
                u = u or {}
                u["long_name" if "long" in path[0] else "short_name"] = v.strip()[:64]
        raw_user = decoded.get("payload")
        if u is None and isinstance(raw_user, str) and raw_user:
            try:
                u = _parse_user(base64.b64decode(raw_user),
                                map_report=(portnum == "MAP_REPORT_APP"))
            except Exception:
                u = None
        if u:
            out["user"] = u
        else:
            out["decode_status"] = "partial"
            out["decode_error"] = "NODEINFO без име (криптиран канал без PSK?)"

    if portnum == "ROUTING_APP":
        # Т16 Касова бележка: Routing{route_request|route_reply|error_reason}
        # — ACK-ът носи request_id = ИД-ТО на оригиналния пакет → директен
        # JOIN входящ пакет ↔ изпълнение (доставено/без следа). Работи и за
        # криптирани канали (метаданно ниво: типа/ID-тата са видими).
        rid = _get(decoded, "routing.route_reply.request_id",
                   "routing.route_request.request_id",
                   "routing.error_reason.request_id",
                   "routing.request_id", "routing.route_reply", "routing.route_request")
        if isinstance(rid, int) and rid > 0:
            out["ack_request_id"] = rid
            reason = _get(decoded, "routing.error_reason.error_reason",
                          "routing.error_reason")
            out["ack_error_reason"] = reason if isinstance(reason, str) else None

    if portnum == "NEIGHBORINFO_APP":
        # NeighborInfo{neighbors:[{node_id, snr}]} — кой кого чува (топология)
        raw = _get(decoded, "neighborinfo.neighbors", "neighborInfo.neighbors",
                   "neighbors")
        neighbors = []
        if isinstance(raw, list):
            for nb in raw:
                if not isinstance(nb, dict):
                    continue
                nid = _get(nb, "node_id", "nodeId")
                snr = nb.get("snr")
                if isinstance(nid, int):
                    neighbors.append({
                        "node": f"!{nid:08x}",
                        "snr": round(float(snr), 1)
                        if isinstance(snr, (int, float)) else None,
                    })
        if neighbors:
            out["neighbors"] = neighbors
        else:
            out["decode_status"] = "partial"
            out["decode_error"] = "neighborinfo без разпознати съседи"

    if portnum == "ROUTING_APP":
        # RouteDiscovery{route:[node_id]} — маршрут при traceroute/next-hop
        route = _get(decoded, "routing.route_reply.route",
                     "routing.routeReply.route")
        if isinstance(route, list) and route and all(
                isinstance(h, int) and h > 0 for h in route):
            out["route"] = [f"!{h:08x}" for h in route]

    if out["packet_type"] is None:
        return None
    return out


# ---------- protobuf ServiceEnvelope — минимален wire парсер (3b, ADR-005) ----------
# Официалните .proto дефиниции са с полета: ServiceEnvelope{1 packet, 2 channel_id,
# 3 gateway_id}; MeshPacket{1 from(f32), 2 to(f32), 3 channel, 4 id, 6 rx_snr(f32),
# 7 rx_rssi, 12 decoded}; Data{1 portnum, 2 payload}; Position{1 latitude_i,
# 2 longitude_i, 3 altitude}; Telemetry{1 device_metrics}; DeviceMetrics{
# 1 battery_level}. Парсерът е умишлено минимален — без protobuf зависимост.

import struct

PORTNUM_ENUM = {
    # автентичните номера от firmware protobufs (portnums.pb.h, 2.6+):
    # TELEMETRY=67, NEIGHBORINFO=71, TRACEROUTE=70, MAP_REPORT=73 …
    1: "TEXT_MESSAGE_APP", 2: "REMOTE_HARDWARE_APP", 3: "POSITION_APP",
    4: "NODEINFO_APP", 5: "ROUTING_APP", 6: "ADMIN_APP",
    7: "TEXT_MESSAGE_COMPRESSED_APP", 8: "WAYPOINT_APP", 9: "AUDIO_APP",
    10: "DETECTION_SENSOR_APP", 11: "ALERT_APP", 12: "KEY_VERIFICATION_APP",
    13: "REMOTE_SHELL_APP", 32: "REPLY_APP", 33: "IP_TUNNEL_APP",
    34: "PAXCOUNTER_APP", 64: "SERIAL_APP", 65: "STORE_FORWARD_APP",
    66: "RANGE_TEST_APP", 67: "TELEMETRY_APP", 68: "ZPS_APP",
    69: "SIMULATOR_APP", 70: "TRACEROUTE_APP", 71: "NEIGHBORINFO_APP",
    72: "ATAK_PLUGIN", 73: "MAP_REPORT_APP", 74: "POWERSTRESS_APP",
}


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while i < len(buf):
        b = buf[i]
        result |= (b & 0x7F) << shift
        i += 1
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint твърде дълъг")
    raise ValueError("varint без край")


def _parse_fields(buf: bytes):
    """Итерира (field_no, wire_type, value). value: int за varint, bytes за LEN,
    int за fixed32/64."""
    i = 0
    while i < len(buf):
        tag, i = _read_varint(buf, i)
        field_no, wire = tag >> 3, tag & 0x07
        if wire == 0:
            value, i = _read_varint(buf, i)
        elif wire == 1:  # fixed64
            value = struct.unpack("<Q", buf[i:i + 8])[0]
            i += 8
        elif wire == 2:  # length-delimited
            ln, i = _read_varint(buf, i)
            if i + ln > len(buf):
                raise ValueError("LEN отвъд буфера")
            value = buf[i:i + ln]
            i += ln
        elif wire == 5:  # fixed32
            value = struct.unpack("<I", buf[i:i + 4])[0]
            i += 4
        else:
            raise ValueError(f"неподдържан wire type {wire}")
        yield field_no, wire, value


def _as_i32(v: int) -> int:
    """int32 поле, прочетено като 64-битов varint (protobuf sign-разширява
    отрицателните int32 до 64 бита) → истинската стойност."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v > 0x7FFFFFFF else v


def _parse_user(inner: bytes, map_report: bool = False) -> dict | None:
    """User protobuf (meshtastic.mesh.User): 2 long_name, 3 short_name,
    5 hw_model (varint), 7 role (varint), 8 public_key (bytes → sha256
    fingerprint, показани първите 4 байта). MapReport (map протокола) има
    СВОЯ номерация: 1 long_name, 2 short_name, 5 hw_model, 6 role —
    map_report=True превключва схемата. None ако няма нито едно име."""
    import struct as _s  # локално — модулът го ползва само тук при нужда
    out: dict = {}
    try:
        fields = list(_parse_fields(inner))
    except (ValueError, OverflowError, IndexError):
        return None  # осакатен varint/структура — честно „няма име"
    f_long = 1 if map_report else 2
    f_short = 2 if map_report else 3
    f_role = 6 if map_report else 7
    for f, _w, v in fields:
        if f in (f_long, f_short) and isinstance(v, bytes):
            try:
                txt = v.decode("utf-8").replace(chr(0), "").strip()
            except UnicodeDecodeError:
                continue
            if txt:
                out["long_name" if f == f_long else "short_name"] = txt[:64]
        elif f == 5 and isinstance(v, int):
            out["hw_model"] = v
        elif f == f_role and isinstance(v, int):
            out["role"] = v
        elif f == 8 and isinstance(v, bytes) and len(v) >= 4:
            out["pubkey_fp"] = hashlib.sha256(v).hexdigest()[:8]
    if not (out.get("long_name") or out.get("short_name")):
        return None
    return out


# --- Т36 срез 2: PSK декрипция (ADR-007) ------------------------------------
# Източници: firmware CryptoEngine.cpp (nonce = packetId uint64 LE [0..7] +
# fromNode uint32 LE [8..11] + 4 нули; CTR с 4-байтов каунтер = последните
# 4 байта на IV; key 16B → AES-128, 32B → AES-256) и Channels.cpp (1-байтов
# PSK с индекс N се разширява до дефолтния ключ, последен байт += N-1).
DEFAULT_PSK = bytes.fromhex("d164898633bc274a9a198761a62ce353")


def expand_psk(raw: bytes) -> bytes | None:
    """1-байтов PSK (индекс) → реален ключ; 16/32B → директно; празно → None.
    Индекс 0 = изключено криптиране; N > 1 = дефолтният ключ с последен
    байт повдигнат с N-1 (Channel.cpp::getKey)."""
    if len(raw) == 1:
        idx = raw[0]
        if idx == 0:
            return None
        key = bytearray(DEFAULT_PSK)
        key[-1] = (key[-1] + idx - 1) & 0xFF
        return bytes(key)
    if len(raw) in (16, 32):
        return raw
    return None


def decrypt_mesh_payload(key: bytes, from_id: int, pkt_id: int,
                         encrypted: bytes, extra_nonce: int = 0) -> bytes | None:
    """AES-CTR декрипция на MeshPacket.encrypted. None при крипто грешка
    (грешният ключ НЕ е изключение — просто дава смислен protobuf или не)."""
    if not key or from_id is None or pkt_id is None or not encrypted:
        return None
    try:
        nonce = pkt_id.to_bytes(8, "little") + (from_id & 0xFFFFFFFF).to_bytes(4, "little") + b"\x00" * 4
        if extra_nonce:
            nonce = nonce[:4] + (extra_nonce & 0xFFFFFFFF).to_bytes(4, "little") + nonce[8:]
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        # CryptoLib CTR(setCounterSize(4)) брои само последните 4 байта от IV —
        # еквивалентно на пълно 16-байтово BE каунър-блоково нарастване,
        # докато горните 12 байта не прелеят (при ≤256B payload — никога)
        c = Cipher(algorithms.AES(key), modes.CTR(nonce))
        return c.decryptor().update(encrypted)
    except Exception:
        return None


def decode_envelope_protobuf(payload: bytes, psk_map: dict | None = None) -> dict | None:
    """Бинарен ServiceEnvelope → същата форма като envelope_info.

    Поддържа ДВА wire формата на MeshPacket (полето Data смяна номера си в
    firmware 2.6 — автентична схема, потвърдена от реален трафик):
    - fw 2.6+: decoded=4, encrypted=5, id=6(f32), rx_time=7, rx_snr=8(f),
      rx_rssi=12(int32), hop_limit=9, hop_start=15
    - по-стари:  decoded=12, encrypted=13, id=4(varint), rx_snr=6(f),
      rx_rssi=7(int32)
    Разпознаването става по това къде седи LEN блокът Data. Криптиран пакет
    (само encrypted, без decoded) е честен „meshtastic-encrypted / partial“ —
    възел/id/SNR/RSSI се извличат, текст не може без PSK ключ.
    None ако изобщо не е ServiceEnvelope."""
    try:
        packet = channel_id = gateway_id = None
        for f, _w, v in _parse_fields(payload):
            if f == 1 and isinstance(v, bytes):
                packet = v
            elif f == 2 and isinstance(v, bytes):
                channel_id = v.decode("utf-8", "replace")
            elif f == 3 and isinstance(v, bytes):
                gateway_id = v.decode("utf-8", "replace")
        if packet is None:
            return None
        fields: dict[int, tuple[int, object]] = {}
        for f, w, v in _parse_fields(packet):
            fields.setdefault(f, (w, v))

        def fbytes(n: int) -> bytes | None:
            v = fields.get(n, (0, None))[1]
            return v if isinstance(v, bytes) else None

        def fint(n: int) -> int | None:
            v = fields.get(n, (0, None))[1]
            return v if isinstance(v, int) else None

        def ffloat(n: int) -> float | None:
            w, v = fields.get(n, (0, None))
            if w == 5 and isinstance(v, int):
                return struct.unpack("<f", struct.pack("<I", v))[0]
            return None

        data = encrypted = None
        was_encrypted = False
        if fbytes(4) is not None or fbytes(5) is not None:
            # firmware 2.6+ номерация (decoded=4, encrypted=5; при криптиран
            # канал поле 4 липсва — тогава се разпознава по encrypted на 5)
            data, encrypted = fbytes(4), fbytes(5)
            pkt_id = fint(6)
            snr = ffloat(8)
            rssi = fint(12)
        elif fbytes(12) is not None or fbytes(13) is not None:
            # по-стара номерация
            data, encrypted = fbytes(12), fbytes(13)
            pkt_id = fint(4)
            snr = ffloat(6)
            rssi = fint(7)
        else:
            return None  # нито decoded, нито encrypted — не е MeshPacket
        from_id = fint(1)
        to_id = fint(2)
        rssi = _as_i32(rssi) if rssi is not None else None
        if data is None:
            if encrypted is not None:
                # Т36 срез 2: PSK декрипция (ADR-007) — ключът е по channel_id
                # на ServiceEnvelope; неуспехът остава честно partial
                key = None
                if psk_map and channel_id:
                    raw = psk_map.get(channel_id) or psk_map.get(channel_id.lower())
                    if isinstance(raw, str) and raw:
                        try:
                            key = expand_psk(base64.b64decode(raw))
                        except Exception:
                            key = None
                    elif isinstance(raw, (bytes, bytearray)):
                        key = expand_psk(bytes(raw))
                clear = decrypt_mesh_payload(key, from_id, pkt_id, encrypted) if key else None
                if clear is not None:
                    # декриптирало е — продължи по НОРМАЛНИЯ път с data=clear
                    data = clear
                    was_encrypted = True
                else:
                    out = {
                        "packet_type": "meshtastic-encrypted",
                        "text": None, "battery": None, "lat": None, "lng": None,
                        "node_id": f"!{from_id:08x}" if from_id is not None else None,
                        "decode_status": "partial",
                        "decode_error": "криптиран канал — без PSK ключ съдържанието"
                                        " не се декодира (възел/id/SNR/RSSI са видими)",
                        "decoder_id": "meshtastic-protobuf",
                        "packet_id": pkt_id, "snr": snr, "rssi": rssi,
                        "channel_id": channel_id, "gateway_id": gateway_id,
                        "broadcast": to_id == 0xFFFFFFFF,
                    }
                    return out
        if data is None:
            return None  # нито decoded, нито encrypted — не е MeshPacket
        portnum = 0
        inner = None
        for f, _w, v in _parse_fields(data):
            if f == 1:
                portnum = v
            elif f == 2 and isinstance(v, bytes):
                inner = v
        pname = PORTNUM_ENUM.get(portnum)
        if pname is None:
            return None  # непозната/невалидна структура — не се преструваме
        out = {
            "packet_type": PORTNUM_TYPES.get(pname, f"meshtastic-{pname.lower()}"),
            "text": None,
            "battery": None,
            "lat": None,
            "lng": None,
            "node_id": f"!{from_id:08x}" if from_id is not None else None,
            "decode_status": "decoded",
            "decode_error": None,
            "decoder_id": "meshtastic-protobuf+psk" if was_encrypted else "meshtastic-protobuf",
            "packet_id": pkt_id,
            "snr": snr,
            "rssi": rssi,
            "channel_id": channel_id,
            "gateway_id": gateway_id,
            "broadcast": to_id == 0xFFFFFFFF,
        }
        # вътрешният payload е чужд — грешка в него прави пакета partial, не
        # фатален (envelope-ът е валиден: тип/източник/id са вече извлечени)
        try:
            if pname == "TEXT_MESSAGE_APP" and inner is not None:
                try:
                    out["text"] = inner.decode("utf-8")
                except UnicodeDecodeError:
                    out["decode_error"] = "текстовото payload не е UTF-8"
                    out["decode_status"] = "partial"
            elif pname == "TELEMETRY_APP" and inner is not None:
                # Telemetry{1 device_metrics{1 battery_level, 2 voltage(f32)}};
                # EnvironmentMetrics и другите варианти не носят батерия
                device_metrics = None
                for f, _w, v in _parse_fields(inner):
                    if f == 1 and isinstance(v, bytes):
                        device_metrics = v
                if device_metrics is not None:
                    for df, _dw, dv in _parse_fields(device_metrics):
                        if df == 1:
                            out["battery"] = dv
                        elif df == 2 and _dw == 5:
                            out["voltage"] = struct.unpack("<f", struct.pack("<I", dv))[0]
                if out["battery"] is None:
                    out["decode_error"] = "телеметрия без device_metrics (възможно е батар. модул)"
                    out["decode_status"] = "partial"
            elif pname == "POSITION_APP" and inner is not None:
                # Position{1 latitude_i, 2 longitude_i, 3 altitude} — int32 ×1e7
                lat_i = lng_i = None
                for f, _w, v in _parse_fields(inner):
                    if f in (1, 2) and isinstance(v, int):
                        if f == 1:
                            lat_i = _as_i32(v)
                        else:
                            lng_i = _as_i32(v)
                if isinstance(lat_i, int) and isinstance(lng_i, int):
                    out["lat"] = round(lat_i / 1e7, 6)
                    out["lng"] = round(lng_i / 1e7, 6)
                else:
                    out["decode_error"] = "позиция без координати"
                    out["decode_status"] = "partial"
            elif pname in ("NODEINFO_APP", "MAP_REPORT_APP"):
                # Т36: User{2 long_name, 3 short_name, 5 hw_model, 7 role,
                # 8 public_key} — номерата от generated user.pb.h. Plaintext
                # при канали без PSK (дефолтният AQ== не криптира); криптиран
                # канал без ключ → честно „без име", не грешка.
                user = (_parse_user(inner, map_report=(pname == "MAP_REPORT_APP"))
                        if inner is not None else None)
                if user:
                    out["user"] = user
                else:
                    out["decode_error"] = ("NODEINFO без разпознаваем User "
                                           "(криптиран канал без PSK?)")
                    out["decode_status"] = "partial"
                out["decode_status"] = "partial"
            elif pname == "NEIGHBORINFO_APP" and inner is not None:
                # NeighborInfo{1 node_id, 2 last_sent_by_id, 3 interval,
                # 4 repeated Neighbor{1 node_id, 2 snr(f32)}} — топология
                neighbors = []
                for f, _w, v in _parse_fields(inner):
                    if f != 4 or not isinstance(v, bytes):
                        continue
                    nid = snr = None
                    for nf, nw, nv in _parse_fields(v):
                        if nf == 1 and isinstance(nv, int):
                            nid = nv
                        elif nf == 2 and nw == 5:
                            snr = struct.unpack("<f", struct.pack("<I", nv))[0]
                    if nid is not None:
                        neighbors.append({
                            "node": f"!{nid:08x}",
                            "snr": round(snr, 1) if snr is not None else None,
                        })
                if neighbors:
                    out["neighbors"] = neighbors
                else:
                    out["decode_error"] = "neighborinfo без разпознати съседи"
                    out["decode_status"] = "partial"
            elif pname == "ROUTING_APP" and inner is not None:
                # Routing{1 route_request, 2 route_reply, 3 error_reason};
                # RouteDiscovery{1 repeated uint32 route, 2 snr_towards};
                # вложените носят request_id (f1) → Т16 касова бележка
                route = None
                ack_id = None
                ack_reason = None
                for f, _w, v in _parse_fields(inner):
                    if f in (1, 2) and isinstance(v, bytes):
                        rid = next((hv for hf, _hw, hv in _parse_fields(v)
                                    if hf == 1 and isinstance(hv, int)), None)
                        if rid and rid > 4:
                            ack_id = rid
                        hops = [hv for hf, _hw, hv in _parse_fields(v)
                                if hf == 1 and isinstance(hv, int) and hv > 0]
                        if len(hops) > 1:
                            route = [f"!{h:08x}" for h in hops]
                    elif f == 3 and isinstance(v, bytes):
                        rr = next((hv for hf, _hw, hv in _parse_fields(v)
                                   if hf == 1), None)
                        if isinstance(rr, int):
                            ack_reason = rr
                if ack_id is not None:
                    out["ack_request_id"] = ack_id
                    out["ack_error_reason"] = ack_reason
                if route:
                    out["route"] = route
        except ValueError:
            out["decode_error"] = "вътрешният payload не се парсира като protobuf"
            out["decode_status"] = "partial"
        return out
    except (ValueError, struct.error):
        return None
