from __future__ import annotations

from datetime import datetime, timezone

from receiptgate.validation_v1 import (
    is_terminal_receipt,
    validate_receipt_payload,
    validate_routing_invariant,
)


def _base_payload(
    *,
    receipt_id: str = "r-1",
    task_id: str = "task-1",
    recipient_ai: str = "agent:a",
    phase: str = "accepted",
    status: str = "NA",
    outcome_kind: str = "NA",
    outcome_text: str = "NA",
    escalation_class: str = "NA",
    escalation_reason: str = "NA",
    escalation_to: str = "NA",
    completed_at: str | None = None,
):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "tenant_id": "tenant-a",
        "receipt_id": receipt_id,
        "task_id": task_id,
        "parent_task_id": "NA",
        "caused_by_receipt_id": "NA",
        "dedupe_key": "NA",
        "attempt": 0,
        "from_principal": "principal:p",
        "for_principal": "principal:p",
        "source_system": "receiptgate-test",
        "recipient_ai": recipient_ai,
        "trust_domain": "test",
        "phase": phase,
        "status": status,
        "realtime": False,
        "task_type": "test.task",
        "task_summary": "Test task",
        "task_body": "Testing receipt validation",
        "inputs": {"test": "data"},
        "expected_outcome_kind": "response_text",
        "expected_artifact_mime": "NA",
        "outcome_kind": outcome_kind,
        "outcome_text": outcome_text,
        "artifact_location": "NA",
        "artifact_pointer": "NA",
        "artifact_checksum": "NA",
        "artifact_size_bytes": 0,
        "artifact_mime": "NA",
        "escalation_class": escalation_class,
        "escalation_reason": escalation_reason,
        "escalation_to": escalation_to,
        "retry_requested": False,
        "body": {
            "summary": "Test receipt",
            "phase": phase,
        },
        "artifact_refs": [],
        "created_at": now,
        "stored_at": now,
        "started_at": None,
        "completed_at": completed_at,
        "read_at": None,
        "archived_at": None,
        "metadata": {},
    }


def test_validate_routing_invariant_escalate_mismatch():
    payload = {
        "phase": "escalate",
        "recipient_ai": "agent:a",
        "escalation_to": "agent:b",
    }
    errors = validate_routing_invariant(payload)
    assert errors
    assert errors[0]["field"] == "recipient_ai"


def test_validate_receipt_payload_accept_requires_na_status():
    payload = _base_payload(status="success")
    errors = validate_receipt_payload(payload)
    assert errors


def test_validate_receipt_payload_complete_requires_status_and_outcome():
    payload = _base_payload(
        phase="complete",
        status="NA",
        outcome_kind="NA",
        outcome_text="NA",
        completed_at=None,
    )
    errors = validate_receipt_payload(payload)
    assert errors


def test_validate_receipt_payload_escalate_requires_fields_and_routing():
    payload = _base_payload(
        phase="escalate",
        escalation_class="NA",
        escalation_reason="NA",
        escalation_to="NA",
    )
    errors = validate_receipt_payload(payload)
    assert errors


def test_validate_receipt_payload_escalate_valid():
    payload = _base_payload(
        phase="escalate",
        recipient_ai="agent:a",
        escalation_to="agent:a",
        escalation_class="policy",
        escalation_reason="lease_expired",
    )
    errors = validate_receipt_payload(payload)
    assert errors == []


def test_terminal_receipt_detection():
    assert is_terminal_receipt({"phase": "accepted"}) is False
    assert is_terminal_receipt({"phase": "complete"}) is True
    assert is_terminal_receipt({"phase": "escalate"}) is True
