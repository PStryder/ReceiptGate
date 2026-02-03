from __future__ import annotations

from receiptgate.principals import (
    INTERNAL_PRINCIPAL_PREFIXES,
    SERVICE_PRINCIPAL_ID,
    SYSTEM_PRINCIPAL_ID,
    is_internal_principal,
)


def test_internal_principals_detected():
    assert is_internal_principal(SYSTEM_PRINCIPAL_ID) is True
    assert is_internal_principal(SERVICE_PRINCIPAL_ID) is True


def test_external_principals_rejected():
    assert is_internal_principal("agent:alpha") is False
    assert is_internal_principal("user:beta") is False


def test_internal_prefixes():
    for prefix in INTERNAL_PRINCIPAL_PREFIXES:
        assert is_internal_principal(f"{prefix}example") is True
