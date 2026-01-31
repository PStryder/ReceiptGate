#!/usr/bin/env python3
"""Golden path demo for ReceiptGate (REST endpoints)."""

from __future__ import annotations

import json
import os
import sys
import time
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


def main() -> int:
    base_url = _env("RECEIPTGATE_URL", "http://localhost:8000")
    api_key = _env("RECEIPTGATE_API_KEY")

    client = HttpClient(base_url, api_key=api_key)

    recipient = _env("RECEIPTGATE_DEMO_RECIPIENT", "agent:demo")
    created_by = _env("RECEIPTGATE_DEMO_CREATED_BY", "worker:demo")
    principal = _env("RECEIPTGATE_DEMO_PRINCIPAL", "agent:demo")

    obligation_id = f"ob-{uuid4()}"
    task_id = f"task-{uuid4()}"

    accepted_receipt_id = f"rcpt-{uuid4()}"
    complete_receipt_id = f"rcpt-{uuid4()}"

    accepted_payload = {
        "receipt_id": accepted_receipt_id,
        "phase": "accepted",
        "obligation_id": obligation_id,
        "caused_by_receipt_id": None,
        "created_by": created_by,
        "recipient": recipient,
        "principal": principal,
        "task_ref": {"task_id": task_id, "queue": "default", "lease_seconds": 60},
        "body": {"summary": "Task accepted"},
    }

    complete_payload = {
        "receipt_id": complete_receipt_id,
        "phase": "complete",
        "obligation_id": obligation_id,
        "caused_by_receipt_id": accepted_receipt_id,
        "created_by": created_by,
        "recipient": recipient,
        "principal": principal,
        "task_ref": {"task_id": task_id, "queue": "default", "lease_seconds": 60},
        "body": {
            "summary": "Task completed",
            "result": {"status": "ok", "reason": "demo"},
        },
    }

    print("Submitting accepted receipt...")
    client.request_json("POST", "/receipts", accepted_payload)

    inbox = client.request_json("GET", f"/inbox/{recipient}")
    inbox_items = inbox.get("items", [])
    if not any(item.get("obligation_id") == obligation_id for item in inbox_items):
        raise RuntimeError("Expected obligation to appear in inbox after accept")

    print("Submitting complete receipt...")
    client.request_json("POST", "/receipts", complete_payload)

    time.sleep(0.5)

    chain = client.request_json("GET", f"/receipts/{complete_receipt_id}/chain")
    chain_ids = [entry.get("receipt_id") for entry in chain.get("chain", [])]
    if accepted_receipt_id not in chain_ids or complete_receipt_id not in chain_ids:
        raise RuntimeError(f"Chain missing receipts: {chain_ids}")

    inbox_after = client.request_json("GET", f"/inbox/{recipient}")
    inbox_items_after = inbox_after.get("items", [])
    if any(item.get("obligation_id") == obligation_id for item in inbox_items_after):
        raise RuntimeError("Obligation still open after completion")

    print("Golden path complete: inbox closed and chain verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
