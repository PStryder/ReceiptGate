from __future__ import annotations

from receiptgate.ledger_v1 import list_inbox, store_receipt


def test_inbox_excludes_terminal_receipts(db_session):
    tenant_id = "tenant-a"
    accepted = {
        "receipt_id": "r-accept",
        "recipient_ai": "agent:a",
        "task_id": "task-1",
        "phase": "accepted",
        "caused_by_receipt_id": "NA",
    }
    store_receipt(db_session, accepted, tenant_id)

    inbox = list_inbox(db_session, tenant_id, "agent:a", limit=10)
    assert inbox["count"] == 1

    complete = {
        "receipt_id": "r-complete",
        "recipient_ai": "agent:a",
        "task_id": "task-1",
        "phase": "complete",
        "caused_by_receipt_id": "r-accept",
    }
    store_receipt(db_session, complete, tenant_id)

    inbox = list_inbox(db_session, tenant_id, "agent:a", limit=10)
    assert inbox["count"] == 0


def test_inbox_is_tenant_scoped(db_session):
    accepted_a = {
        "receipt_id": "r-a",
        "recipient_ai": "agent:a",
        "task_id": "task-a",
        "phase": "accepted",
        "caused_by_receipt_id": "NA",
    }
    accepted_b = {
        "receipt_id": "r-b",
        "recipient_ai": "agent:a",
        "task_id": "task-b",
        "phase": "accepted",
        "caused_by_receipt_id": "NA",
    }
    store_receipt(db_session, accepted_a, "tenant-a")
    store_receipt(db_session, accepted_b, "tenant-b")

    inbox_a = list_inbox(db_session, "tenant-a", "agent:a", limit=10)
    inbox_b = list_inbox(db_session, "tenant-b", "agent:a", limit=10)

    assert {r["receipt_id"] for r in inbox_a["receipts"]} == {"r-a"}
    assert {r["receipt_id"] for r in inbox_b["receipts"]} == {"r-b"}
