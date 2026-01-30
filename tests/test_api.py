from __future__ import annotations


def _accepted_payload(
    receipt_id: str,
    obligation_id: str,
    task_id: str,
    recipient: str = "agent:a",
):
    return {
        "receipt_id": receipt_id,
        "phase": "accepted",
        "obligation_id": obligation_id,
        "caused_by_receipt_id": None,
        "created_by": recipient,
        "recipient": recipient,
        "principal": "principal:p",
        "task_ref": {"task_id": task_id},
        "body": {},
    }


def _complete_payload(
    receipt_id: str,
    obligation_id: str,
    task_id: str,
    recipient: str = "agent:a",
    caused_by_receipt_id: str | None = None,
):
    return {
        "receipt_id": receipt_id,
        "phase": "complete",
        "obligation_id": obligation_id,
        "caused_by_receipt_id": caused_by_receipt_id,
        "created_by": recipient,
        "recipient": recipient,
        "principal": "principal:p",
        "task_ref": {"task_id": task_id},
        "body": {"result": {"status": "ok"}},
    }


def test_post_receipt_accepts_valid(api_client):
    payload = _accepted_payload("r-1", "obl-1", "task-1")
    response = api_client.post("/receipts", json=payload)
    assert response.status_code == 201
    assert response.json()["receipt_id"] == "r-1"


def test_post_receipt_idempotent_replay_returns_200(api_client):
    payload = _accepted_payload("r-2", "obl-2", "task-2")
    response = api_client.post("/receipts", json=payload)
    assert response.status_code == 201

    response = api_client.post("/receipts", json=payload)
    assert response.status_code == 200
    assert response.json()["idempotent_replay"] is True


def test_post_receipt_conflict_returns_409(api_client):
    payload = _accepted_payload("r-3", "obl-3", "task-3")
    response = api_client.post("/receipts", json=payload)
    assert response.status_code == 201

    conflict = dict(payload)
    conflict["body"] = {"summary": "different"}
    response = api_client.post("/receipts", json=conflict)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECEIPT_ID_COLLISION"


def test_inbox_returns_open_obligations(api_client):
    accepted = _accepted_payload("r-4", "obl-4", "task-4")
    response = api_client.post("/receipts", json=accepted)
    assert response.status_code == 201

    inbox = api_client.get("/inbox/agent:a")
    assert inbox.status_code == 200
    assert inbox.json()["items"]

    complete = _complete_payload(
        "r-4c",
        "obl-4",
        "task-4",
        caused_by_receipt_id="r-4",
    )
    response = api_client.post("/receipts", json=complete)
    assert response.status_code == 201

    inbox = api_client.get("/inbox/agent:a")
    assert inbox.status_code == 200
    assert inbox.json()["items"] == []


def test_receipt_chain_traversal(api_client):
    accepted = _accepted_payload("r-5", "obl-5", "task-5")
    response = api_client.post("/receipts", json=accepted)
    assert response.status_code == 201

    complete = _complete_payload(
        "r-5c",
        "obl-5",
        "task-5",
        caused_by_receipt_id="r-5",
    )
    response = api_client.post("/receipts", json=complete)
    assert response.status_code == 201

    chain = api_client.get("/receipts/r-5c/chain")
    assert chain.status_code == 200
    data = chain.json()
    assert [item["receipt_id"] for item in data["chain"]] == ["r-5", "r-5c"]


def test_receipts_search_filters_by_phase_and_task(api_client):
    accepted = _accepted_payload("r-6", "obl-6", "task-6")
    response = api_client.post("/receipts", json=accepted)
    assert response.status_code == 201

    complete = _complete_payload(
        "r-6c",
        "obl-6",
        "task-6",
        caused_by_receipt_id="r-6",
    )
    response = api_client.post("/receipts", json=complete)
    assert response.status_code == 201

    response = api_client.post(
        "/receipts/search",
        json={"task_id": "task-6", "phase": "accepted"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["receipts"][0]["receipt_id"] == "r-6"
