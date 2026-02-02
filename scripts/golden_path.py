#!/usr/bin/env python3
"""Golden path demo for ReceiptGate (MCP JSON-RPC)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


class HttpClient:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            query = {k: v for k, v in query.items() if v is not None}
            if query:
                url = f"{url}?{urlencode(query)}"

        data = None
        if payload is not None:
            data = json.dumps(payload, default=str).encode("utf-8")

        req = Request(url, data=data, method=method)
        for key, value in self.headers.items():
            req.add_header(key, value)

        try:
            with urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed: {exc.code} {exc.reason}: {detail}") from None

        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def mcp_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }
        response = self.request_json("POST", "/mcp", payload)
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response.get("result", {})


def _build_receipt(
    *,
    receipt_id: str,
    task_id: str,
    phase: str,
    status: str,
    recipient_ai: str,
    caused_by_receipt_id: str = "NA",
    outcome_kind: str = "NA",
    outcome_text: str = "NA",
) -> dict[str, Any]:
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
        "from_principal": recipient_ai,
        "for_principal": recipient_ai,
        "source_system": "receiptgate-demo",
        "recipient_ai": recipient_ai,
        "trust_domain": "demo",
        "phase": phase,
        "status": status,
        "realtime": False,
        "task_type": "demo.task",
        "task_summary": f"Demo task {phase}",
        "task_body": f"Golden path {phase}",
        "inputs": {},
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
        "created_at": now,
        "stored_at": None,
        "started_at": now if phase == "accepted" else None,
        "completed_at": completed_at,
        "read_at": None,
        "archived_at": None,
        "metadata": {},
    }


def main() -> int:
    base_url = _env("RECEIPTGATE_URL", "http://localhost:8000")
    api_key = _env("RECEIPTGATE_API_KEY")

    client = HttpClient(base_url, api_key=api_key)

    recipient = _env("RECEIPTGATE_DEMO_RECIPIENT", "agent:demo")
    task_id = f"task-{uuid4()}"

    accepted_receipt_id = f"rcpt-{uuid4()}"
    complete_receipt_id = f"rcpt-{uuid4()}"

    accepted_payload = _build_receipt(
        receipt_id=accepted_receipt_id,
        task_id=task_id,
        phase="accepted",
        status="NA",
        recipient_ai=recipient,
    )

    complete_payload = _build_receipt(
        receipt_id=complete_receipt_id,
        task_id=task_id,
        phase="complete",
        status="success",
        recipient_ai=recipient,
        caused_by_receipt_id=accepted_receipt_id,
        outcome_kind="response_text",
        outcome_text="Demo complete",
    )

    print("Submitting accepted receipt (MCP)...")
    client.mcp_call("receiptgate.submit_receipt", {"receipt": accepted_payload})

    inbox = client.mcp_call("receiptgate.list_inbox", {"recipient_ai": recipient, "limit": 20})
    inbox_items = inbox.get("receipts", [])
    if not any(item.get("task_id") == task_id for item in inbox_items):
        raise RuntimeError("Expected obligation to appear in inbox after accept")

    print("Submitting complete receipt (MCP)...")
    client.mcp_call("receiptgate.submit_receipt", {"receipt": complete_payload})

    time.sleep(0.5)

    chain = client.mcp_call("receiptgate.get_receipt_chain", {"receipt_id": complete_receipt_id})
    chain_ids = [entry.get("receipt_id") for entry in chain.get("chain", [])]
    if accepted_receipt_id not in chain_ids or complete_receipt_id not in chain_ids:
        raise RuntimeError(f"Chain missing receipts: {chain_ids}")

    inbox_after = client.mcp_call("receiptgate.list_inbox", {"recipient_ai": recipient, "limit": 20})
    inbox_items_after = inbox_after.get("receipts", [])
    if any(item.get("task_id") == task_id for item in inbox_items_after):
        raise RuntimeError("Obligation still open after completion")

    print("Golden path complete: inbox closed and chain verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
