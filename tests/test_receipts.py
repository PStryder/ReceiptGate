from __future__ import annotations

from datetime import datetime, timezone

import pytest

from receiptgate.ledger_v1 import ReceiptConflictError, put_receipt


def _receipt_payload(
    *,
    receipt_id: str,
    task_id: str,
    recipient_ai: str,
    created_at: str | None = None,
    task_summary: str = "Test task",
):
    now = created_at or datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
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
        "phase": "accepted",
        "status": "NA",
        "realtime": False,
        "task_type": "test.task",
        "task_summary": task_summary,
        "task_body": "Testing receipt storage",
        "inputs": {"test": "data"},
        "expected_outcome_kind": "response_text",
        "expected_artifact_mime": "NA",
        "outcome_kind": "NA",
        "outcome_text": "NA",
        "artifact_location": "NA",
        "artifact_pointer": "NA",
        "artifact_checksum": "NA",
        "artifact_size_bytes": 0,
        "artifact_mime": "NA",
        "escalation_class": "NA",
        "escalation_reason": "NA",
        "escalation_to": "NA",
        "retry_requested": False,
        "created_at": now,
        "stored_at": None,
        "started_at": None,
        "completed_at": None,
        "read_at": None,
        "archived_at": None,
        "metadata": {},
    }


def test_put_receipt_idempotent_replay(db_session):
    payload = _receipt_payload(receipt_id="r-accepted", task_id="task-1", recipient_ai="agent:a")
    result = put_receipt(db_session, payload, "tenant-a")
    assert result["idempotent_replay"] is False

    replay = put_receipt(db_session, payload, "tenant-a")
    assert replay["idempotent_replay"] is True


def test_put_receipt_collision_raises(db_session):
    payload = _receipt_payload(receipt_id="r-collision", task_id="task-2", recipient_ai="agent:a")
    put_receipt(db_session, payload, "tenant-a")

    mutated = _receipt_payload(
        receipt_id="r-collision",
        task_id="task-2",
        recipient_ai="agent:a",
        task_summary="Different summary",
    )
    with pytest.raises(ReceiptConflictError):
        put_receipt(db_session, mutated, "tenant-a")


def test_put_receipt_created_at_affects_hash(db_session):
    payload = _receipt_payload(
        receipt_id="r-created-at",
        task_id="task-3",
        recipient_ai="agent:a",
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
    )
    put_receipt(db_session, payload, "tenant-a")

    mutated = _receipt_payload(
        receipt_id="r-created-at",
        task_id="task-3",
        recipient_ai="agent:a",
        created_at=datetime(2026, 2, 2, tzinfo=timezone.utc).isoformat(),
    )
    with pytest.raises(ReceiptConflictError):
        put_receipt(db_session, mutated, "tenant-a")


def test_put_receipt_allows_same_id_different_tenant(db_session):
    payload = _receipt_payload(receipt_id="r-shared", task_id="task-7", recipient_ai="agent:a")
    result_a = put_receipt(db_session, payload, "tenant-a")
    assert result_a["idempotent_replay"] is False

    mutated = _receipt_payload(
        receipt_id="r-shared",
        task_id="task-7",
        recipient_ai="agent:a",
        task_summary="Different summary",
    )
    result_b = put_receipt(db_session, mutated, "tenant-b")
    assert result_b["idempotent_replay"] is False
