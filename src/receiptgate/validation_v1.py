"""Validation helpers for LegiVellum receipt schema v1."""

from __future__ import annotations

import json
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
    root = Path(__file__).resolve().parents[2]
    return root / "schema" / "receipt.schema.v1.json"


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
        return []

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
