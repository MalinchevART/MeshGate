"""Т36 срез 2 (ADR-007): PSK декрипция — чисти функции + синтетичен
криптиран ServiceEnvelope (конструиран наобратно с СЪЩИЯ nonce формат).
Живата проверка с дефолтния LongFast ключ върху реален BG трафик е отделна."""

import base64

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.ingest.mesh_decode import (
    DEFAULT_PSK,
    decode_envelope_protobuf,
    decrypt_mesh_payload,
    expand_psk,
)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num: int, wire: int, payload: bytes) -> bytes:
    return _varint((num << 3) | wire) + payload


def _ld(num: int, data: bytes) -> bytes:
    return _field(num, 2, _varint(len(data)) + data)


def _vi(num: int, n: int) -> bytes:
    return _field(num, 0, _varint(n))


def _encrypt(key: bytes, from_id: int, pkt_id: int, plaintext: bytes) -> bytes:
    nonce = pkt_id.to_bytes(8, "little") + from_id.to_bytes(4, "little") + b"\x00" * 4
    c = Cipher(algorithms.AES(key), modes.CTR(nonce))
    return c.encryptor().update(plaintext)


# ---------- expand_psk --------------------------------------------------------

def test_expand_default_index_one():
    assert expand_psk(b"\x01") == DEFAULT_PSK


def test_expand_index_bumps_last_byte():
    key = expand_psk(b"\x03")
    assert key[:-1] == DEFAULT_PSK[:-1]
    assert key[-1] == (DEFAULT_PSK[-1] + 2) & 0xFF


def test_expand_zero_is_off_and_direct_keys_pass():
    assert expand_psk(b"\x00") is None
    assert expand_psk(bytes(range(16))) == bytes(range(16))
    assert expand_psk(bytes(range(32))) == bytes(range(32))
    assert expand_psk(b"garbage!!") is None  # 9 байта — невалидно


# ---------- decrypt_mesh_payload ----------------------------------------------

def test_roundtrip_decrypt():
    key = bytes(range(16))
    plain = b"meshgate-test"
    enc = _encrypt(key, 0x11223344, 0x0102030405060708, plain)
    assert decrypt_mesh_payload(key, 0x11223344, 0x0102030405060708, enc) == plain


def test_decrypt_wrong_key_gives_wrong_bytes_not_error():
    enc = _encrypt(bytes(range(16)), 1, 2, b"secret")
    out = decrypt_mesh_payload(bytes(range(16, 32)), 1, 2, enc)
    assert out is not None and out != b"secret"


# ---------- крайъгълен: криптиран ServiceEnvelope → декодиран -----------------

def _envelope(pkt_id: int, from_id: int, channel: str, encrypted: bytes) -> bytes:
    packet = (
        _vi(1, from_id)              # from
        + _vi(2, 0xFFFFFFFF)         # to = broadcast
        + _ld(5, encrypted)          # encrypted (fw 2.6+)
        + _vi(6, pkt_id)             # id
    )
    return (
        _ld(1, packet)
        + _ld(2, channel.encode())
        + _ld(3, b"!testgate")
    )


def test_envelope_decrypted_with_psk_map():
    key = bytes(range(16))
    data = _vi(1, 1) + _ld(2, "здравей от криптирания канал".encode())  # TEXT_MESSAGE_APP
    pkt_id, from_id = 0xAABBCCDD, 0xEB7C62A9
    enc = _encrypt(key, from_id, pkt_id, data)
    out = decode_envelope_protobuf(
        _envelope(pkt_id, from_id, "TestCh", enc),
        psk_map={"TestCh": base64.b64encode(key).decode()})
    assert out is not None
    assert out["packet_type"] == "meshtastic-text"
    assert out["decode_status"] == "decoded"
    assert out["decoder_id"] == "meshtastic-protobuf+psk"
    assert out["text"] == "здравей от криптирания канал"
    assert out["node_id"] == "!eb7c62a9"


def test_envelope_without_key_stays_partial():
    key = bytes(range(16))
    data = _vi(1, 1) + _ld(2, b"hi")
    pkt_id, from_id = 0xAABBCCDD, 0xEB7C62A9
    enc = _encrypt(key, from_id, pkt_id, data)
    out = decode_envelope_protobuf(_envelope(pkt_id, from_id, "TestCh", enc))
    assert out is not None
    assert out["packet_type"] == "meshtastic-encrypted"
    assert out["decode_status"] == "partial"


def test_envelope_wrong_key_stays_partial():
    key = bytes(range(16))
    data = _vi(1, 1) + _ld(2, b"hi")
    enc = _encrypt(key, 0xEB7C62A9, 0xAABBCCDD, data)
    wrong = bytes(range(16, 32))
    out = decode_envelope_protobuf(
        _envelope(0xAABBCCDD, 0xEB7C62A9, "TestCh", enc),
        psk_map={"TestCh": base64.b64encode(wrong).decode()})
    # грешният ключ дава „декриптирани“ байтове, но не е валиден SubPacket —
    # декодерът трябва да НЕ се преструва: портът е невалиден → partial/None
    assert out is None or out["packet_type"] == "meshtastic-encrypted"
