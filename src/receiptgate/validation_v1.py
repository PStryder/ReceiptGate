"""Validation helpers for LegiVellum receipt schema v1."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import jsonschema
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False


FIELD_SIZE_LIMITS = {
    "inputs": 64 * 1024,
    "metadata": 16 * 1024,
    "task_body": 100 * 1024,
    "outcome_text": 100 * 1024,
}

TERMINAL_PHASES = {"complete", "escalate"}


def _schema_path() -> Path:
    """Locate the receipt schema in both installed and checkout layouts.

    parents[2] is the repo root in a source checkout but the site-packages
    parent once installed, so an installed ReceiptGate looked for the schema at
    /usr/local/lib/python3.11/schema and never found it. The schema ships
    inside the package (see the wheel force-include in pyproject.toml), so
    prefer that and fall back to the repo layout for editable installs.
    """
    override = os.environ.get("RECEIPTGATE_SCHEMA_DIR")
    if override:
        return Path(override) / "receipt.schema.v1.json"

    packaged = Path(__file__).resolve().parent / "schema" / "receipt.schema.v1.json"
    if packaged.is_file():
        return packaged

    return Path(__file__).resolve().parents[2] / "schema" / "receipt.schema.v1.json"


def _json_size_bytes(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str).encode("utf-8"))
    except Exception:
        return len(str(value).encode("utf-8"))


def validate_field_sizes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for field, limit in FIELD_SIZE_LIMITS.items():
        if field not in payload:
            continue
        size = _json_size_bytes(payload[field])
        if size > limit:
            errors.append({
                "field": field,
                "constraint": f"max_size_{limit}",
                "message": f"{field} exceeds size limit of {limit} bytes (got {size})",
            })
    return errors


def validate_routing_invariant(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if payload.get("phase") == "escalate":
        if payload.get("recipient_ai") != payload.get("escalation_to"):
            errors.append({
                "field": "recipient_ai",
                "constraint": "routing_invariant",
                "message": "recipient_ai must equal escalation_to for phase=escalate",
            })
    return errors


def validate_json_schema(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not JSONSCHEMA_AVAILABLE:
        return []

    schema_path = _schema_path()
    if not schema_path.exists():
        # Failing open here silently disabled every phase rule in
        # receipt.rules.md for any deployment that could not find the file --
        # accepted receipts with terminal status, completions with no
        # completed_at, and artifact claims with no pointer were all stored
        # without complaint. A validator that cannot find its rules is
        # misconfigured, not permissive.
        raise RuntimeError(
            f"Receipt schema not found at {schema_path}; refusing to validate "
            "receipts without it. Set RECEIPTGATE_SCHEMA_DIR to override."
        )

    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        return [{
            "field": ".".join(str(p) for p in exc.path) if exc.path else "unknown",
            "constraint": "json_schema",
            "message": f"JSON Schema validation failed: {exc.message}",
        }]
    return []


def validate_receipt_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate receipt payload against schema + invariants."""
    errors: list[dict[str, Any]] = []
    errors.extend(validate_json_schema(payload))
    errors.extend(validate_field_sizes(payload))
    errors.extend(validate_routing_invariant(payload))
    return errors


def is_terminal_receipt(payload: dict[str, Any]) -> bool:
    """Return True if payload represents a terminal receipt."""
    return payload.get("phase") in TERMINAL_PHASES


def apply_server_fields(payload: dict[str, Any], *, tenant_id: str, stored_at: str) -> dict[str, Any]:
    """Apply server-assigned fields without mutating input."""
    updated = dict(payload)
    updated["tenant_id"] = tenant_id
    updated["stored_at"] = stored_at
    return updated
