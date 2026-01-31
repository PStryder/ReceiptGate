"""ReceiptGate v1 ledger storage helpers (LegiVellum schema)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import bindparam, text

from receiptgate.validation_v1 import TERMINAL_PHASES

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_receipt(db, payload: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    stored_at = _now_iso()
    receipt_id = payload.get("receipt_id")
    if not receipt_id:
        raise ValueError("receipt_id is required")

    record = {
        "uuid": str(uuid4()),
        "tenant_id": tenant_id,
        "receipt_id": receipt_id,
        "stored_at": stored_at,
        "recipient_ai": payload.get("recipient_ai", "NA"),
        "task_id": payload.get("task_id", "NA"),
        "phase": payload.get("phase", "accepted"),
        "caused_by_receipt_id": payload.get("caused_by_receipt_id", "NA"),
        "archived_at": payload.get("archived_at"),
        "payload": json.dumps(payload, default=str),
    }

    try:
        db.execute(
            text(
                """
                INSERT INTO receipts_v1 (
                    uuid, tenant_id, receipt_id, stored_at, recipient_ai, task_id,
                    phase, caused_by_receipt_id, archived_at, payload
                )
                VALUES (
                    :uuid, :tenant_id, :receipt_id, :stored_at, :recipient_ai, :task_id,
                    :phase, :caused_by_receipt_id, :archived_at, :payload
                )
                """
            ),
            record,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "receiptgate_v1_receipt_stored",
        receipt_id=receipt_id,
        tenant_id=tenant_id,
        task_id=record.get("task_id"),
        phase=record.get("phase"),
        recipient_ai=record.get("recipient_ai"),
        caused_by_receipt_id=record.get("caused_by_receipt_id"),
    )

    return {"receipt_id": receipt_id, "stored_at": stored_at, "tenant_id": tenant_id}


def list_inbox(db, tenant_id: str, recipient_ai: str, limit: int = 20) -> dict[str, Any]:
    terminal_phases = sorted(TERMINAL_PHASES)
    query = text(
        """
        SELECT receipt_id, task_id, phase, stored_at
        FROM receipts_v1 r
        WHERE tenant_id = :tenant_id
          AND recipient_ai = :recipient_ai
          AND phase = 'accepted'
          AND archived_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM receipts_v1 t
            WHERE t.tenant_id = r.tenant_id
              AND t.task_id = r.task_id
              AND t.phase IN :terminal_phases
          )
        ORDER BY stored_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("terminal_phases", expanding=True))
    rows = db.execute(
        query,
        {
            "tenant_id": tenant_id,
            "recipient_ai": recipient_ai,
            "limit": limit,
            "terminal_phases": terminal_phases,
        },
    ).mappings().all()

    return {
        "tenant_id": tenant_id,
        "recipient_ai": recipient_ai,
        "count": len(rows),
        "receipts": [dict(row) for row in rows],
    }


def list_task_receipts(
    db,
    tenant_id: str,
    task_id: str,
    sort: str = "asc",
    include_payload: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    sort_order = "ASC" if sort.lower() == "asc" else "DESC"
    limit_clause = "LIMIT :limit" if limit else ""
    params: dict[str, Any] = {"tenant_id": tenant_id, "task_id": task_id}
    if limit:
        params["limit"] = limit

    rows = db.execute(
        text(
            f"""
            SELECT receipt_id, phase, stored_at, recipient_ai, task_id, payload
            FROM receipts_v1
            WHERE tenant_id = :tenant_id AND task_id = :task_id
            ORDER BY stored_at {sort_order}
            {limit_clause}
            """
        ),
        params,
    ).mappings().all()

    receipts: list[dict[str, Any]] = []
    for row in rows:
        payload = {}
        if row.get("payload"):
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                payload = {}
        entry = {
            "receipt_id": row.get("receipt_id"),
            "phase": row.get("phase"),
            "stored_at": row.get("stored_at"),
            "recipient_ai": row.get("recipient_ai"),
            "task_id": row.get("task_id"),
        }
        if payload.get("created_at"):
            entry["created_at"] = payload.get("created_at")
        if include_payload:
            entry["payload"] = payload
        receipts.append(entry)

    return {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "receipts": receipts,
    }


def get_receipt(db, tenant_id: str, receipt_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT payload, stored_at
            FROM receipts_v1
            WHERE tenant_id = :tenant_id AND receipt_id = :receipt_id
            """
        ),
        {"tenant_id": tenant_id, "receipt_id": receipt_id},
    ).mappings().first()
    if not row:
        return None

    payload = {}
    if row.get("payload"):
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError:
            payload = {}
    if "stored_at" not in payload:
        payload["stored_at"] = row.get("stored_at")
    return payload


def search_receipts(
    db,
    tenant_id: str,
    root_task_id: str,
    phase: str | None = None,
    recipient_ai: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    conditions = ["tenant_id = :tenant_id", "task_id = :root_task_id"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "root_task_id": root_task_id, "limit": limit}

    if phase:
        conditions.append("phase = :phase")
        params["phase"] = phase
    if recipient_ai:
        conditions.append("recipient_ai = :recipient_ai")
        params["recipient_ai"] = recipient_ai
    if since:
        conditions.append("stored_at >= :since")
        params["since"] = since

    where_clause = " AND ".join(conditions)
    rows = db.execute(
        text(
            f"""
            SELECT receipt_id, phase, stored_at, recipient_ai, task_id, payload
            FROM receipts_v1
            WHERE {where_clause}
            ORDER BY stored_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    receipts: list[dict[str, Any]] = []
    for row in rows:
        payload = {}
        if row.get("payload"):
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                payload = {}
        receipts.append({
            "receipt_id": row.get("receipt_id"),
            "phase": row.get("phase"),
            "stored_at": row.get("stored_at"),
            "tenant_id": tenant_id,
            "task_id": row.get("task_id"),
            "recipient_ai": row.get("recipient_ai"),
            "created_at": payload.get("created_at"),
        })

    return {
        "tenant_id": tenant_id,
        "root_task_id": root_task_id,
        "receipts": receipts,
    }


def _get_receipt_row(db, tenant_id: str, receipt_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT receipt_id, caused_by_receipt_id, stored_at
            FROM receipts_v1
            WHERE tenant_id = :tenant_id AND receipt_id = :receipt_id
            """
        ),
        {"tenant_id": tenant_id, "receipt_id": receipt_id},
    ).mappings().first()
    return dict(row) if row else None


def get_receipt_chain(
    db,
    tenant_id: str,
    receipt_id: str,
    max_depth: int = 2048,
) -> dict[str, Any]:
    chain: list[dict[str, Any]] = []
    current_id = receipt_id
    depth = 0

    while current_id and current_id != "NA" and depth < max_depth:
        row = _get_receipt_row(db, tenant_id, current_id)
        if not row:
            break
        chain.append({
            "receipt_id": row["receipt_id"],
            "caused_by_receipt_id": row.get("caused_by_receipt_id") or "NA",
            "stored_at": row.get("stored_at"),
        })
        current_id = row.get("caused_by_receipt_id")
        depth += 1

    return {"root_receipt_id": receipt_id, "chain": chain}
