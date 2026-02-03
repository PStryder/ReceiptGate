from __future__ import annotations

from receiptgate.utils import canonical_hash


def test_canonical_hash_omits_created_at_when_disabled():
    payload = {
        "receipt_id": "r-1",
        "task_id": "task-1",
        "created_at": "2026-02-01T00:00:00Z",
        "value": {"b": 1, "a": 2},
    }
    _, digest_a = canonical_hash(payload, include_created_at=False)

    mutated = dict(payload)
    mutated["created_at"] = "2026-02-02T00:00:00Z"
    _, digest_b = canonical_hash(mutated, include_created_at=False)

    assert digest_a == digest_b


def test_canonical_hash_includes_created_at_when_enabled():
    payload = {
        "receipt_id": "r-2",
        "task_id": "task-2",
        "created_at": "2026-02-01T00:00:00Z",
        "value": {"b": 1, "a": 2},
    }
    _, digest_a = canonical_hash(payload, include_created_at=True)

    mutated = dict(payload)
    mutated["created_at"] = "2026-02-02T00:00:00Z"
    _, digest_b = canonical_hash(mutated, include_created_at=True)

    assert digest_a != digest_b


def test_canonical_hash_is_order_invariant():
    payload_a = {"a": 1, "b": {"x": 2, "y": 3}}
    payload_b = {"b": {"y": 3, "x": 2}, "a": 1}

    canonical_a, digest_a = canonical_hash(payload_a, include_created_at=True)
    canonical_b, digest_b = canonical_hash(payload_b, include_created_at=True)

    assert canonical_a == canonical_b
    assert digest_a == digest_b
