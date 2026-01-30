from __future__ import annotations

from receiptgate.validation_v1 import is_terminal_receipt, validate_routing_invariant


def test_validate_routing_invariant_escalate_mismatch():
    payload = {
        "phase": "escalate",
        "recipient_ai": "agent:a",
        "escalation_to": "agent:b",
    }
    errors = validate_routing_invariant(payload)
    assert errors
    assert errors[0]["field"] == "recipient_ai"


def test_terminal_receipt_detection():
    assert is_terminal_receipt({"phase": "accepted"}) is False
    assert is_terminal_receipt({"phase": "complete"}) is True
    assert is_terminal_receipt({"phase": "escalate"}) is True
