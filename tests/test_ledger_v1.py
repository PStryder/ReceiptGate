"""Inbox behaviour, derived from committed custody rather than from receipts.

Rewritten for Phase 2. These previously called `store_receipt` directly and
asserted against a query that selected `accepted` receipts and excluded any
whose *task_id* carried a terminal receipt. That query was wrong in two
directions -- it lost fan-out obligations and delivered nothing on escalation --
so testing it faithfully would only pin the defect.

The inbox is now a view over canonical custody state, which exists only because
a transition committed. So these go through the notary, which is also the point:
an obligation appears in an inbox because ReceiptGate committed an acceptance,
not because a row was written somewhere.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from legivellum.authority import Principal

from receiptgate.ledger_v1 import list_inbox, put_receipt

ACTOR = Principal(id="svc:test", role="service", visibility="tenant-a")


def _receipt(
    *,
    receipt_id: str,
    task_id: str,
    obligation_id: str,
    executor: str,
    phase: str = "accepted",
    caused_by: str = "NA",
    tenant_id: str = "tenant-a",
):
    """A canonical receipt.

    `for_principal` is the executor -- the party that owes the work -- and is
    what custody derives from. `recipient_ai` is the inbox owner for this one
    receipt; on an accepted obligation the two coincide.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "tenant_id": tenant_id,
        "receipt_id": receipt_id,
        "task_id": task_id,
        "obligation_id": obligation_id,
        "parent_task_id": "NA",
        "caused_by_receipt_id": caused_by,
        "dedupe_key": "NA",
        "attempt": 0,
        "from_principal": executor if phase != "accepted" else "principal:requester",
        "for_principal": executor,
        "source_system": "svc:test",
        "recipient_ai": executor,
        "trust_domain": "test",
        "phase": phase,
        "status": "success" if phase == "complete" else "NA",
        "realtime": False,
        "task_type": "test.task",
        "task_summary": "s",
        "task_body": "b",
        "inputs": {},
        "expected_outcome_kind": "response_text",
        "expected_artifact_mime": "NA",
        "outcome_kind": "response_text" if phase == "complete" else "NA",
        "outcome_text": "done" if phase == "complete" else "NA",
        "artifact_location": "NA",
        "artifact_pointer": "NA",
        "artifact_checksum": "NA",
        "artifact_size_bytes": 0,
        "artifact_mime": "NA",
        "escalation_class": "NA",
        "escalation_reason": "NA",
        "escalation_to": "NA",
        "retry_requested": False,
        "body": {},
        "created_at": now,
        "stored_at": None,
        "started_at": now,
        "completed_at": now if phase == "complete" else None,
        "read_at": None,
        "archived_at": None,
        "metadata": {},
    }


def _actor_for(tenant_id: str, actor_id: str = "svc:test") -> Principal:
    return Principal(id=actor_id, role="service", visibility=tenant_id)


def test_accepted_obligation_appears_in_the_custodian_inbox(db_session):
    put_receipt(
        db_session,
        _receipt(
            receipt_id="r-accept",
            task_id="task-1",
            obligation_id="obl-1",
            executor="agent:a",
        ),
        "tenant-a",
        actor=ACTOR,
    )
    inbox = list_inbox(db_session, "tenant-a", "agent:a", limit=10)
    assert inbox["count"] == 1
    assert inbox["receipts"][0]["obligation_id"] == "obl-1"


def test_completing_removes_it_from_the_inbox(db_session):
    put_receipt(
        db_session,
        _receipt(
            receipt_id="r-accept",
            task_id="task-1",
            obligation_id="obl-1",
            executor="agent:a",
        ),
        "tenant-a",
        actor=ACTOR,
    )
    put_receipt(
        db_session,
        _receipt(
            receipt_id="r-complete",
            task_id="task-1",
            obligation_id="obl-1",
            executor="agent:a",
            phase="complete",
            caused_by="r-accept",
        ),
        "tenant-a",
        actor=ACTOR,
    )
    assert list_inbox(db_session, "tenant-a", "agent:a", limit=10)["count"] == 0


def test_one_completion_does_not_discharge_a_sibling_obligation(db_session):
    """The fan-out defect, asserted directly.

    Two executors accept the SAME task_id as separate obligations. Alice
    completing hers must not empty Bob's inbox. Under the old query the
    NOT EXISTS correlated on task_id, so it did exactly that -- Bob was left
    holding an obligation no query could surface and no completion had closed.
    """
    shared_task = "task-contract-42"
    for name, obligation in (("agent:alice", "obl-alice"), ("agent:bob", "obl-bob")):
        put_receipt(
            db_session,
            _receipt(
                receipt_id=f"r-accept-{name}",
                task_id=shared_task,
                obligation_id=obligation,
                executor=name,
            ),
            "tenant-a",
            actor=ACTOR,
        )

    assert list_inbox(db_session, "tenant-a", "agent:alice", limit=10)["count"] == 1
    assert list_inbox(db_session, "tenant-a", "agent:bob", limit=10)["count"] == 1

    put_receipt(
        db_session,
        _receipt(
            receipt_id="r-complete-alice",
            task_id=shared_task,
            obligation_id="obl-alice",
            executor="agent:alice",
            phase="complete",
            caused_by="r-accept-agent:alice",
        ),
        "tenant-a",
        actor=ACTOR,
    )

    assert list_inbox(db_session, "tenant-a", "agent:alice", limit=10)["count"] == 0
    assert list_inbox(db_session, "tenant-a", "agent:bob", limit=10)["count"] == 1, (
        "Bob's obligation was discharged by Alice's completion; terminator "
        "detection is matching on task_id rather than obligation_id"
    )


def test_inbox_is_tenant_scoped(db_session):
    put_receipt(
        db_session,
        _receipt(
            receipt_id="r-a",
            task_id="task-a",
            obligation_id="obl-a",
            executor="agent:a",
            tenant_id="tenant-a",
        ),
        "tenant-a",
        actor=_actor_for("tenant-a"),
    )
    put_receipt(
        db_session,
        _receipt(
            receipt_id="r-b",
            task_id="task-b",
            obligation_id="obl-b",
            executor="agent:a",
            tenant_id="tenant-b",
        ),
        "tenant-b",
        actor=_actor_for("tenant-b"),
    )

    inbox_a = list_inbox(db_session, "tenant-a", "agent:a", limit=10)
    inbox_b = list_inbox(db_session, "tenant-b", "agent:a", limit=10)

    assert {r["obligation_id"] for r in inbox_a["receipts"]} == {"obl-a"}
    assert {r["obligation_id"] for r in inbox_b["receipts"]} == {"obl-b"}
