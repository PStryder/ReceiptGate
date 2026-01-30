from __future__ import annotations

from datetime import datetime, timezone

import pytest

from receiptgate.errors import ReceiptGateError
from receiptgate.models import (
    CompletionResult,
    EscalationBody,
    ReceiptAccepted,
    ReceiptBody,
    ReceiptComplete,
    ReceiptEscalate,
    TaskRef,
)
from receiptgate.receipts import _compute_canonical, put_receipt


def _accepted_receipt(
    *,
    receipt_id: str = "r-accepted",
    obligation_id: str = "obl-1",
    task_id: str = "task-1",
    recipient: str = "agent:a",
    created_by: str = "agent:a",
) -> ReceiptAccepted:
    return ReceiptAccepted(
        receipt_id=receipt_id,
        phase="accepted",
        obligation_id=obligation_id,
        caused_by_receipt_id=None,
        created_by=created_by,
        recipient=recipient,
        principal="principal:p",
        task_ref=TaskRef(task_id=task_id),
        body=ReceiptBody(summary="accepted"),
    )


def _complete_receipt(
    *,
    receipt_id: str = "r-complete",
    obligation_id: str = "obl-1",
    task_id: str = "task-1",
    recipient: str = "agent:a",
    created_by: str = "agent:a",
    caused_by_receipt_id: str | None = None,
) -> ReceiptComplete:
    return ReceiptComplete(
        receipt_id=receipt_id,
        phase="complete",
        obligation_id=obligation_id,
        caused_by_receipt_id=caused_by_receipt_id,
        created_by=created_by,
        recipient=recipient,
        principal="principal:p",
        task_ref=TaskRef(task_id=task_id),
        body=ReceiptBody(result=CompletionResult(status="ok")),
    )


def _escalate_receipt(
    *,
    receipt_id: str = "r-escalate",
    obligation_id: str = "obl-1",
    task_id: str = "task-1",
    recipient: str = "agent:a",
    created_by: str = "agent:a",
    parent_receipt_id: str = "r-accepted",
    parent_obligation_id: str = "obl-1",
    child_obligation_id: str = "obl-child",
) -> ReceiptEscalate:
    escalation = EscalationBody.model_validate(
        {
            "parent_receipt_id": parent_receipt_id,
            "parent_obligation_id": parent_obligation_id,
            "child_obligation_id": child_obligation_id,
            "from": created_by,
            "to": recipient,
            "reason": "needs help",
        }
    )
    return ReceiptEscalate(
        receipt_id=receipt_id,
        phase="escalate",
        obligation_id=obligation_id,
        caused_by_receipt_id=None,
        created_by=created_by,
        recipient=recipient,
        principal="principal:p",
        task_ref=TaskRef(task_id=task_id),
        body=ReceiptBody(escalation=escalation),
    )


def test_canonical_hash_includes_created_at_when_present():
    receipt = _accepted_receipt()
    _, hash_without_time = _compute_canonical(receipt)
    stamped = receipt.model_copy(
        update={"created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    )
    _, hash_with_time = _compute_canonical(stamped)
    assert hash_without_time != hash_with_time


def test_phase_transition_accept_to_complete(db_session):
    accepted = _accepted_receipt()
    _, status = put_receipt(db_session, accepted)
    assert status == 201

    complete = _complete_receipt(caused_by_receipt_id=accepted.receipt_id)
    _, status = put_receipt(db_session, complete)
    assert status == 201


def test_phase_transition_accept_to_escalate(db_session):
    accepted = _accepted_receipt()
    _, status = put_receipt(db_session, accepted)
    assert status == 201

    escalate = _escalate_receipt(parent_receipt_id=accepted.receipt_id)
    _, status = put_receipt(db_session, escalate)
    assert status == 201


def test_idempotent_replay_returns_200(db_session):
    receipt = _accepted_receipt()
    _, status = put_receipt(db_session, receipt)
    assert status == 201

    response, status = put_receipt(db_session, receipt)
    assert status == 200
    assert response.idempotent_replay is True


def test_receipt_id_collision_returns_409(db_session):
    receipt = _accepted_receipt()
    _, status = put_receipt(db_session, receipt)
    assert status == 201

    mutated = receipt.model_copy(update={"body": ReceiptBody(summary="changed")})
    with pytest.raises(ReceiptGateError) as exc_info:
        put_receipt(db_session, mutated)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "RECEIPT_ID_COLLISION"
