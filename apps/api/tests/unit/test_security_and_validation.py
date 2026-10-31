"""Модулни тестове: пароли/сесии/роли и SSRF валидация."""

import socket

import pytest
from fastapi import HTTPException

from app.security import ROLE_ORDER, hash_password, new_session_token, verify_password
from app.routes.bridges import validate_remote_host


def test_password_hash_roundtrip():
    h = hash_password("парола-123")
    assert h != "парола-123"
    assert verify_password("парола-123", h)
    assert not verify_password("грешна", h)


def test_session_token_pair():
    token, token_hash = new_session_token()
    assert token and token_hash and token != token_hash
    token2, _ = new_session_token()
    assert token2 != token


def test_role_ordering():
    assert ROLE_ORDER["viewer"] < ROLE_ORDER["operator"] < ROLE_ORDER["admin"]


class FakeSockAddr:
    def __init__(self, *parts):
        self.parts = parts

    def __getitem__(self, i):
        return self.parts[i]

    def __len__(self):
        return len(self.parts)


def fake_resolver(ips):
    def resolve(host, _port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", FakeSockAddr(ip, 1234)) for ip in ips]
    return resolve


def test_ssrf_blocks_private_addresses():
    for ip in ("10.0.0.5", "192.168.1.10", "127.0.0.1", "169.254.1.1", "172.16.0.1"):
        with pytest.raises(HTTPException) as exc:
            validate_remote_host("evil.example", False, resolver=fake_resolver([ip]))
        assert "ssrf_blocked" in exc.value.detail


def test_ssrf_blocks_localhost_name():
    with pytest.raises(HTTPException) as exc:
        validate_remote_host("LocalHost", False, resolver=fake_resolver(["127.0.0.1"]))
    assert "ssrf_blocked" in exc.value.detail


def test_ssrf_allows_public_address():
    validate_remote_host("broker.example.net", False, resolver=fake_resolver(["93.184.216.34"]))


def test_ssrf_internal_needs_explicit_allow():
    validate_remote_host("internal.broker", True, resolver=fake_resolver(["10.1.2.3"]))
    with pytest.raises(HTTPException):
        validate_remote_host("internal.broker", False, resolver=fake_resolver(["10.1.2.3"]))


def test_ssrf_nonexistent_host():
    def dead(host, port):
        raise socket.gaierror("nope")
    with pytest.raises(HTTPException) as exc:
        validate_remote_host("no.such.host.invalid", False, resolver=dead)
    assert "ssrf_blocked" in exc.value.detail
