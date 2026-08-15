"""Utility helpers for ReceiptGate."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def canonical_hash(payload: dict[str, Any], include_created_at: bool) -> tuple[str, str]:
    """
    Compute canonical JSON and sha256 hash for a receipt payload.

    When created_at is server-generated, omit it from the canonical hash to keep
    idempotency stable across replays.
    """
    canonical_payload = copy.deepcopy(payload)
    if not include_created_at:
        canonical_payload.pop("created_at", None)

    canonical_json = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return canonical_json, f"sha256:{digest}"


def json_size_bytes(data: Any) -> int:
    """Return byte size of JSON-serialized data using canonical separators."""
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    return len(payload.encode("utf-8"))

