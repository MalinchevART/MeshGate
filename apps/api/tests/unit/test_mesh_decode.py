"""Модулни тестове на Meshtastic разпознаването (docs/10-meshtastic-mqtt.md)."""

from app.ingest.mesh_decode import (
    envelope_info,
    is_meshtastic_topic,
    topic_parts,
)


def test_topic_detection_and_parts():
    assert is_meshtastic_topic("msh/EU_868/2/e/LongFast/!a4b1c2d3e4f5")
    assert not is_meshtastic_topic("mesh/emul/node1/up")
    parts = topic_parts("msh/emul/2/e/LongFast/!a4b1c2d3e4f5")
    assert parts == {"region": "emul", "channel": "LongFast", "node": "!a4b1c2d3e4f5"}
    # JSON вариант и старият /c/
    assert topic_parts("msh/US/2/json/admin/!abcd1234")["channel"] == "admin"
    assert topic_parts("msh/US/2/c/LongFast/!abcd1234")["channel"] == "LongFast"
    # тема без канал
    assert topic_parts("msh/US/2/map/")["channel"] is None


def _env(portnum, decoded_extra=None, **top):
    import json

    doc = {
        "id": 1, "timestamp": 1700000000, "to": -1, "from": 123456789,
        "sender": "!abcd1234", "channel": 0,
        "decoded": {"portnum": portnum, **(decoded_extra or {})},
        **top,
    }
    return json.dumps(doc)


def test_text_message_plain_and_base64():
    info = envelope_info(_env("TEXT_MESSAGE_APP", {"text": "здравей"}))
    assert info["packet_type"] == "meshtastic-text"
    assert info["text"] == "здравей"
    assert info["node_id"] == "!abcd1234"

    import base64

    b64 = base64.b64encode("пакет от хълма".encode()).decode()
    info2 = envelope_info(_env("TEXT_MESSAGE_APP", {"payload": b64}))
    assert info2["text"] == "пакет от хълма"

    info3 = envelope_info(_env("TEXT_MESSAGE_APP", {"payload": "%%%"}))
    assert info3["decode_status"] == "partial"


def test_telemetry_battery_snake_and_camel():
    snake = envelope_info(_env("TELEMETRY_APP", {
        "telemetry": {"device_metrics": {"battery_level": 77}},
    }))
    assert snake["packet_type"] == "meshtastic-telemetry"
    assert snake["battery"] == 77

    camel = envelope_info(_env("TELEMETRY_APP", {
        "telemetry": {"deviceMetrics": {"batteryLevel": 12}},
    }))
    assert camel["battery"] == 12


def test_position_degrees():
    info = envelope_info(_env("POSITION_APP", {
        "position": {"latitude_i": 426977000, "longitude_i": 233219000},
    }))
    assert info["packet_type"] == "meshtastic-position"
    assert abs(info["lat"] - 42.6977) < 1e-4
    assert abs(info["lng"] - 23.3219) < 1e-4


def test_unknown_portnum_and_non_json():
    info = envelope_info(_env("PAXCOUNTER_APP", {"pax": 3}))
    assert info["packet_type"] == "meshtastic-paxcounter"
    assert envelope_info("не json") is None
    assert envelope_info('{"друго": 1}') is None


# ---------- 3b: бинарен protobuf ServiceEnvelope ----------

def _varint(n: int) -> bytes:
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _fld(no: int, wt: int) -> bytes:
    return _varint((no << 3) | wt)


def _pb_env(portnum: int, inner: bytes, from_id=0x2C1A5B3C, to=0xFFFFFFFF, pkt_id=77) -> bytes:
    data = _fld(1, 0) + _varint(portnum) + _fld(2, 2) + _varint(len(inner)) + inner
    pkt = (
        _fld(1, 5) + from_id.to_bytes(4, "little")
        + _fld(2, 5) + to.to_bytes(4, "little")
        + _fld(4, 0) + _varint(pkt_id)
        + _fld(12, 2) + _varint(len(data)) + data
    )
    return _fld(1, 2) + _varint(len(pkt)) + pkt


def test_protobuf_text_message_decoded_fully():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    info = decode_envelope_protobuf(_pb_env(1, "пакет от реална мрежа".encode()))
    assert info["packet_type"] == "meshtastic-text"
    assert info["node_id"] == "!2c1a5b3c"
    assert info["text"] == "пакет от реална мрежа"
    assert info["packet_id"] == 77
    assert info["broadcast"] is True
    assert info["decoder_id"] == "meshtastic-protobuf"


def test_protobuf_telemetry_battery_full():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    dm = _fld(1, 0) + _varint(81)  # DeviceMetrics.battery_level = 81
    tele = _fld(1, 2) + _varint(len(dm)) + dm  # Telemetry.device_metrics
    # TELEMETRY_APP = 67 (автентичният номер от firmware portnums)
    info = decode_envelope_protobuf(_pb_env(67, tele))
    assert info["packet_type"] == "meshtastic-telemetry"
    assert info["battery"] == 81
    assert info["decode_status"] == "decoded"


def test_protobuf_telemetry_environment_partial_and_garbage_none():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    env_metrics = _fld(2, 2) + _varint(0)  # EnvironmentMetrics (без батерия)
    info = decode_envelope_protobuf(_pb_env(67, env_metrics))
    assert info["packet_type"] == "meshtastic-telemetry"
    assert info["decode_status"] == "partial"
    assert "без device_metrics" in info["decode_error"]
    # боклук не се преструва, че е envelope
    assert decode_envelope_protobuf(b"\xff\xfe\x99garbage") is None
    assert decode_envelope_protobuf(b"") is None


def _varint_i32(n: int) -> bytes:
    # protobuf кодира отрицателно int32 sign-extended до 64 бита
    return _varint(n if n >= 0 else n + (1 << 64))


def test_protobuf_position_with_negative_longitude():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    inner = (
        _fld(1, 0) + _varint_i32(426977000)
        + _fld(2, 0) + _varint_i32(-233219000)
    )
    info = decode_envelope_protobuf(_pb_env(3, inner))
    assert info["packet_type"] == "meshtastic-position"
    assert abs(info["lat"] - 42.6977) < 1e-4
    assert abs(info["lng"] + 23.3219) < 1e-4
    assert info["decode_status"] == "decoded"


def test_protobuf_rssi_negative():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    inner = b"pos"
    data = _fld(1, 0) + _varint(3) + _fld(2, 2) + _varint(len(inner)) + inner
    pkt = (
        _fld(1, 5) + (0x2C1A5B3C).to_bytes(4, "little")
        + _fld(7, 0) + _varint_i32(-102)
        + _fld(12, 2) + _varint(len(data)) + data
    )
    info = decode_envelope_protobuf(_fld(1, 2) + _varint(len(pkt)) + pkt)
    assert info["rssi"] == -102


def test_nested_proto3_json_envelope():
    """proto3-JSON форма: {packet:{from,id,rx_snr,decoded{...}}, channel_id, gateway_id}."""
    import json as _json

    doc = {
        "channel_id": "LongFast", "gateway_id": "gw-1",
        "packet": {
            "from": 739523260, "to": 4294967295, "id": 512,
            "rx_snr": 8.5, "rx_rssi": -97,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "от вложен json"},
        },
    }
    info = envelope_info(_json.dumps(doc))
    assert info["packet_type"] == "meshtastic-text"
    assert info["text"] == "от вложен json"
    assert info["node_id"] == f"!{739523260:08x}"
    assert info["packet_id"] == 512
    assert info["snr"] == 8.5
    assert info["rssi"] == -97
    assert info["channel_id"] == "LongFast"
    assert info["gateway_id"] == "gw-1"
    assert info["broadcast"] is True


def test_flat_json_envelope_packet_id_and_broadcast():
    import json as _json

    doc = {
        "id": 99, "to": -1, "from": 123456789, "sender": "!abcd1234",
        "decoded": {"portnum": "POSITION_APP",
                    "position": {"latitude_i": 426977000, "longitude_i": 233219000}},
    }
    info = envelope_info(_json.dumps(doc))
    assert info["packet_id"] == 99
    assert info["broadcast"] is True
    assert abs(info["lat"] - 42.6977) < 1e-4


# ---------- 3b: дедупликация по packet id в ingest ----------

def test_mesh_duplicate_logic():
    from app.ingest.service import IngestService

    svc = IngestService(pool=None, bridge=None)
    mesh = {"packet_id": 55, "node_id": "!abcd1234"}

    # чисти входящи (local/bridge:*) → повторът се реже
    assert svc.mesh_duplicate("local", mesh) is False      # първо копие
    assert svc.mesh_deduped == 0
    assert svc.mesh_duplicate("local", mesh) is True       # повтор
    assert svc.mesh_deduped == 1
    assert svc.mesh_duplicate("bridge:7", mesh) is True     # друг мост, същият пакет

    # препращания от собствените правила са легитимни нови публикации
    assert svc.mesh_duplicate("routing:3", mesh) is False

    # без packet id няма какво да се дедупликира
    assert svc.mesh_duplicate("local", {"packet_id": None}) is False
    assert svc.mesh_duplicate("local", None) is False

    # различен възел със същото id е различен пакет (32-битовите id се въртят)
    assert svc.mesh_duplicate("local", {"packet_id": 55, "node_id": "!eeee1111"}) is False


# ---------- firmware 2.6+ wire формат + реални прихванати пакети ----------

def _pb_env_v2(portnum: int, inner: bytes, from_id=0x2C1A5B3C, pkt_id=0xA1B2C3D4,
               snr_bits=0x41700000, rssi=-106) -> bytes:
    """Нова номерация: decoded=4, id=6 (fixed32), rx_snr=8 (float),
    rx_rssi=12 (int32, sign-extended varint)."""
    import struct as _s

    data = _fld(1, 0) + _varint(portnum) + _fld(2, 2) + _varint(len(inner)) + inner
    pkt = (
        _fld(1, 5) + from_id.to_bytes(4, "little")
        + _fld(2, 5) + (0xFFFFFFFF).to_bytes(4, "little")
        + _fld(4, 2) + _varint(len(data)) + data
        + _fld(6, 5) + pkt_id.to_bytes(4, "little")
        + _fld(8, 5) + _s.pack("<I", snr_bits)
        + _fld(12, 0) + _varint_i32(rssi)
    )
    return _fld(1, 2) + _varint(len(pkt)) + pkt


def test_protobuf_v2_text_message_and_snr():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    info = decode_envelope_protobuf(_pb_env_v2(1, "нов формат".encode()))
    assert info["packet_type"] == "meshtastic-text"
    assert info["text"] == "нов формат"
    assert info["node_id"] == "!2c1a5b3c"
    assert info["packet_id"] == 0xA1B2C3D4
    assert abs(info["snr"] - 15.0) < 0.1
    assert info["rssi"] == -106
    assert info["decode_status"] == "decoded"


def test_protobuf_v2_telemetry_battery():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    dm = _fld(1, 0) + _varint(64)
    tele = _fld(1, 2) + _varint(len(dm)) + dm
    info = decode_envelope_protobuf(_pb_env_v2(67, tele))
    assert info["packet_type"] == "meshtastic-telemetry"
    assert info["battery"] == 64
    assert info["decode_status"] == "decoded"


# ---------- топология: NeighborInfo (71) и Routing route_reply ----------

def test_neighborinfo_json_flat_and_camel():
    info = envelope_info(_env("NEIGHBORINFO_APP", {
        "neighborinfo": {
            "node_id": 123456789,
            "neighbors": [
                {"node_id": 739523260, "snr": -9.24},
                {"nodeId": 111111, "snr": 5.5},
                {"node_id": "не-число"},  # боклук се прескача
            ],
        },
    }))
    assert info["packet_type"] == "meshtastic-neighbor"
    assert info["neighbors"][0] == {"node": f"!{739523260:08x}", "snr": -9.2}
    assert info["neighbors"][1]["node"] == f"!{111111:08x}"
    assert len(info["neighbors"]) == 2
    assert info["decode_status"] == "decoded"

    # празен neighborinfo → честен partial
    empty = envelope_info(_env("NEIGHBORINFO_APP", {"neighborinfo": {}}))
    assert empty["decode_status"] == "partial"
    assert "съседи" in empty["decode_error"]


def test_neighborinfo_protobuf_v2():
    import struct as _s
    from app.ingest.mesh_decode import decode_envelope_protobuf

    def _nb(nid: int, snr: float) -> bytes:
        return (_fld(1, 0) + _varint(nid)
                + _fld(2, 5) + _s.pack("<I", _s.unpack("<I", _s.pack("<f", snr))[0]))

    n1, n2 = 0x2C1A5B3C, 0x12345678
    inner = (
        _fld(1, 0) + _varint(0x2C1A5B3C)
        + _fld(4, 2) + _varint(len(_nb(n1, -7.5))) + _nb(n1, -7.5)
        + _fld(4, 2) + _varint(len(_nb(n2, 3.0))) + _nb(n2, 3.0)
    )
    info = decode_envelope_protobuf(_pb_env_v2(71, inner))
    assert info["packet_type"] == "meshtastic-neighbor"
    assert info["node_id"] == f"!{0x2C1A5B3C:08x}"
    assert info["neighbors"] == [
        {"node": f"!{n1:08x}", "snr": -7.5},
        {"node": f"!{n2:08x}", "snr": 3.0},
    ]
    assert info["decode_status"] == "decoded"


def test_routing_route_reply_protobuf():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    # RouteDiscovery{route=1: [hop1, hop2]} в Routing.route_reply=2
    route = _fld(1, 0) + _varint(0x2C1A5B3C) + _fld(1, 0) + _varint(0x12345678)
    inner = _fld(2, 2) + _varint(len(route)) + route
    info = decode_envelope_protobuf(_pb_env_v2(5, inner))
    assert info["packet_type"] == "meshtastic-routing"
    assert info["route"] == [f"!{0x2C1A5B3C:08x}", f"!{0x12345678:08x}"]


# реални прихванати пакети от mqtt.meshtastic.vip (мост BG-Mesh, 2026-10-17):
# криптирани канали Bulgaria/Sofia — без PSK ключ, но възел/id/SNR/RSSI се виждат
REAL_ENCRYPTED_V2 = [
    ("0a550d70361eb815ffffffff18252a231b6ba86b0733703c9602a60d5146b2311138d10a44ae2a"
     "b7530cb810da5df35f173fc635b21d70933d43b2d36a4500005841480260e1ffffffffffffffff01"
     "7802980170a80101120842756c67617269611a09216261366137663634",
     "!b81e3670", "Bulgaria", 13.5, -31),
    ("0a8b010d043f3bb015ffffffff18502a587219d3a5f739ce170583b4926a27b904002c9f48cf05"
     "cace2b66f9f8767b8d0bcae4c8bf12f045b38bd8fc5ad0d91bae20b578241f42de7de73658a78f6"
     "9e7c4b47afca2f7dc5583712cc15b903b25e88b20dea45b01b9563509748d623d3cb2d36a450000"
     "c0bf48026096ffffffffffffffff0178029801e401a801011205536f6669611a09213164653964633030",
     "!b03b3f04", "Sofia", -1.5, -106),
]


def test_real_encrypted_packets_recognized():
    from app.ingest.mesh_decode import decode_envelope_protobuf

    for hx, node, channel, snr, rssi in REAL_ENCRYPTED_V2:
        info = decode_envelope_protobuf(bytes.fromhex(hx))
        assert info is not None, hx[:20]
        assert info["packet_type"] == "meshtastic-encrypted", info
        assert info["node_id"] == node, info
        assert info["channel_id"] == channel, info
        assert info["decode_status"] == "partial"
        assert info["snr"] == snr, info
        assert info["rssi"] == rssi, info
        assert info["packet_id"], info
