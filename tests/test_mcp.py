from __future__ import annotations

from datetime import datetime, timezone


def _receipt_payload(
    *,
    receipt_id: str,
    task_id: str,
    recipient_ai: str,
    phase: str = "accepted",
    status: str = "NA",
    caused_by_receipt_id: str = "NA",
    outcome_kind: str = "NA",
    outcome_text: str = "NA",
):
    now = datetime.now(timezone.utc).isoformat()
    completed_at = now if phase == "complete" else None
    return {
        "schema_version": "1.0",
        "receipt_id": receipt_id,
        "task_id": task_id,
        "parent_task_id": "NA",
        "caused_by_receipt_id": caused_by_receipt_id,
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
        "task_summary": f"Test task {phase}",
        "task_body": "Testing receipt storage",
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
        "escalation_class": "NA",
        "escalation_reason": "NA",
        "escalation_to": "NA",
        "retry_requested": False,
        "body": {
            "summary": f"Test receipt {receipt_id}",
            "phase": phase,
        },
        "artifact_refs": [],
        "created_at": now,
        "stored_at": None,
        "started_at": now if phase == "accepted" else None,
        "completed_at": completed_at,
        "read_at": None,
        "archived_at": None,
        "metadata": {},
    }


def _mcp_raw(mcp_client, name: str, arguments: dict):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    return mcp_client.post("/mcp", json=payload).json()


def _mcp_call(mcp_client, name: str, arguments: dict):
    response = _mcp_raw(mcp_client, name, arguments)
    assert "error" not in response, response.get("error")
    return response.get("result", {})


def test_submit_receipt_accepts_valid(mcp_client):
    payload = _receipt_payload(
        receipt_id="r-1",
        task_id="task-1",
        recipient_ai="agent:a",
    )
    result = _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": payload})
    assert result["receipt_id"] == "r-1"
    assert result["idempotent_replay"] is False


def test_submit_receipt_idempotent_replay_returns_ok(mcp_client):
    payload = _receipt_payload(
        receipt_id="r-2",
        task_id="task-2",
        recipient_ai="agent:a",
    )
    result = _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": payload})
    assert result["idempotent_replay"] is False

    result = _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": payload})
    assert result["idempotent_replay"] is True


def test_submit_receipt_conflict_returns_error(mcp_client):
    payload = _receipt_payload(
        receipt_id="r-3",
        task_id="task-3",
        recipient_ai="agent:a",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": payload})

    conflict = dict(payload)
    conflict["task_summary"] = "Different summary"
    response = _mcp_raw(mcp_client, "receiptgate.submit_receipt", {"receipt": conflict})
    assert response["error"]["code"] == "RECEIPT_ID_COLLISION"


def test_inbox_returns_open_obligations(mcp_client):
    accepted = _receipt_payload(
        receipt_id="r-4",
        task_id="task-4",
        recipient_ai="agent:a",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": accepted})

    inbox = _mcp_call(mcp_client, "receiptgate.list_inbox", {"recipient_ai": "agent:a", "limit": 50})
    assert any(item.get("task_id") == "task-4" for item in inbox.get("receipts", []))

    complete = _receipt_payload(
        receipt_id="r-4c",
        task_id="task-4",
        recipient_ai="agent:a",
        phase="complete",
        status="success",
        caused_by_receipt_id="r-4",
        outcome_kind="response_text",
        outcome_text="done",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": complete})

    inbox = _mcp_call(mcp_client, "receiptgate.list_inbox", {"recipient_ai": "agent:a", "limit": 50})
    assert all(item.get("task_id") != "task-4" for item in inbox.get("receipts", []))


def test_receipt_chain_traversal(mcp_client):
    accepted = _receipt_payload(
        receipt_id="r-5",
        task_id="task-5",
        recipient_ai="agent:a",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": accepted})

    complete = _receipt_payload(
        receipt_id="r-5c",
        task_id="task-5",
        recipient_ai="agent:a",
        phase="complete",
        status="success",
        caused_by_receipt_id="r-5",
        outcome_kind="response_text",
        outcome_text="done",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": complete})

    chain = _mcp_call(mcp_client, "receiptgate.get_receipt_chain", {"receipt_id": "r-5c"})
    chain_ids = [item["receipt_id"] for item in chain.get("chain", [])]
    assert chain_ids == ["r-5c", "r-5"]


def test_receipts_search_filters_by_phase_and_task(mcp_client):
    accepted = _receipt_payload(
        receipt_id="r-6",
        task_id="task-6",
        recipient_ai="agent:a",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": accepted})

    complete = _receipt_payload(
        receipt_id="r-6c",
        task_id="task-6",
        recipient_ai="agent:a",
        phase="complete",
        status="success",
        caused_by_receipt_id="r-6",
        outcome_kind="response_text",
        outcome_text="done",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": complete})

    response = _mcp_call(
        mcp_client,
        "receiptgate.search_receipts",
        {"root_task_id": "task-6", "phase": "accepted"},
    )
    assert len(response.get("receipts", [])) == 1
    assert response["receipts"][0]["receipt_id"] == "r-6"


def test_bootstrap_returns_inbox(mcp_client):
    accepted = _receipt_payload(
        receipt_id="r-7",
        task_id="task-7",
        recipient_ai="agent:z",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": accepted})

    response = _mcp_call(
        mcp_client,
        "receiptgate.bootstrap",
        {"agent_name": "agent:z", "session_id": "sess-1"},
    )
    inbox = response.get("inbox", {})
    assert inbox.get("recipient_ai") == "agent:z"
    assert any(item.get("task_id") == "task-7" for item in inbox.get("receipts", []))


def test_list_task_receipts_include_payload(mcp_client):
    accepted = _receipt_payload(
        receipt_id="r-8",
        task_id="task-8",
        recipient_ai="agent:a",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": accepted})

    complete = _receipt_payload(
        receipt_id="r-8c",
        task_id="task-8",
        recipient_ai="agent:a",
        phase="complete",
        status="success",
        caused_by_receipt_id="r-8",
        outcome_kind="response_text",
        outcome_text="done",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": complete})

    response = _mcp_call(
        mcp_client,
        "receiptgate.list_task_receipts",
        {"task_id": "task-8", "include_payload": True},
    )
    assert len(response.get("receipts", [])) == 2
    assert "payload" in response["receipts"][0]


def test_get_receipt_returns_payload(mcp_client):
    payload = _receipt_payload(
        receipt_id="r-9",
        task_id="task-9",
        recipient_ai="agent:a",
    )
    _mcp_call(mcp_client, "receiptgate.submit_receipt", {"receipt": payload})

    result = _mcp_call(
        mcp_client,
        "receiptgate.get_receipt",
        {"receipt_id": "r-9"},
    )
    assert result["receipt_id"] == "r-9"
