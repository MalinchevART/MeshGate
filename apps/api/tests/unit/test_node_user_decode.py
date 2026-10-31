"""Т36 (първи срез): User protobuf decode — имена на възлите."""
from __future__ import annotations

from app.ingest.mesh_decode import _parse_user


def _venc(value: int) -> bytes:
    """protobuf varint енкодер (за тестовите фикстури)."""
    out = bytearray()
    while True:
        b7 = value & 0x7F
        value >>= 7
        out.append(b7 | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _venc((field << 3) | wire)


def _len_delim(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _venc(len(payload)) + payload


def _varint_field(field: int, value: int) -> bytes:
    return _tag(field, 0) + _venc(value)


def test_user_full():
    inner = (
        _len_delim(2, "Ратко планински".encode("utf-8"))
        + _len_delim(3, b"RAT")
        + _varint_field(5, 30)   # hw_model
        + _varint_field(7, 3)    # role: client
        + _len_delim(8, b"\x01\x02\x03\x04pk")
    )
    u = _parse_user(inner)
    assert u["long_name"] == "Ратко планински"
    assert u["short_name"] == "RAT"
    assert u["hw_model"] == 30
    assert u["role"] == 3
    assert u["pubkey_fp"] and len(u["pubkey_fp"]) == 8


def test_user_only_short():
    u = _parse_user(_len_delim(3, b"TLT"))
    assert u["short_name"] == "TLT"
    assert "long_name" not in u


def test_user_without_names_is_none():
    # само hw_model — не е достатъчно за идентичност
    assert _parse_user(_varint_field(5, 30)) is None
    # боклук
    assert _parse_user(b"\xff\xff\xff") is None


def test_user_nul_and_garbage_tolerated():
    # NUL-падинг в short_name (реално се случва по air)
    u = _parse_user(_len_delim(3, b"AB\x00\x00"))
    assert u["short_name"] == "AB"
    # невалиден UTF-8 в long_name — прескача се, short остава
    u2 = _parse_user(_len_delim(2, b"\xff\xfe\xfd") + _len_delim(3, b"OK"))
    assert u2["short_name"] == "OK"
    assert "long_name" not in u2
