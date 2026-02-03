from __future__ import annotations

import pytest
from fastapi import HTTPException

from pydantic import SecretStr

from receiptgate.auth import API_KEY_PREFIX, generate_api_key, verify_api_key
from receiptgate.config import settings


def test_generate_api_key_prefix():
    key = generate_api_key()
    assert key.startswith(API_KEY_PREFIX)
    assert len(key) > len(API_KEY_PREFIX)


def test_verify_api_key_allows_insecure_dev(monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_dev", True)
    assert verify_api_key() is True


def test_verify_api_key_missing_header_raises(monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_dev", False)
    monkeypatch.setattr(settings, "api_key", SecretStr("rg_test"))

    with pytest.raises(HTTPException) as exc:
        verify_api_key(authorization=None, x_api_key=None)

    assert exc.value.status_code == 401


def test_verify_api_key_invalid_header_raises(monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_dev", False)
    monkeypatch.setattr(settings, "api_key", SecretStr("rg_test"))

    with pytest.raises(HTTPException) as exc:
        verify_api_key(authorization="Bearer rg_wrong")

    assert exc.value.status_code == 401


def test_verify_api_key_valid_header(monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_dev", False)
    monkeypatch.setattr(settings, "api_key", SecretStr("rg_test"))

    assert verify_api_key(authorization="Bearer rg_test") is True


def test_verify_api_key_misconfigured_raises(monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_dev", False)
    monkeypatch.setattr(settings, "api_key", SecretStr(""))

    with pytest.raises(HTTPException) as exc:
        verify_api_key(authorization="Bearer rg_test")

    assert exc.value.status_code == 503
