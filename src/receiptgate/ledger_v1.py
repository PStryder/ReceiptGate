"""ReceiptGate v1 ledger storage helpers (LegiVellum schema)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from legivellum.authority import Principal
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from receiptgate import notary
from receiptgate.utils import canonical_hash

logger = logging.getLogger(__name__)


class ReceiptConflictError(Exception):
    def __init__(self, *, receipt_id: str, existing_hash: str, incoming_hash: str) -> None:
        self.receipt_id = receipt_id
        self.existing_hash = existing_hash
        self.incoming_hash = incoming_hash
        super().__init__("receipt_id collision with different canonical hash")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_payload(payload: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(payload)
    canonical.pop("stored_at", None)
    canonical.pop("tenant_id", None)
    return canonical


def _canonical_receipt_hash(payload: dict[str, Any]) -> str:
    canonical_payload = _canonical_payload(payload)
    include_created_at = canonical_payload.get("created_at") is not None
    _, digest = canonical_hash(canonical_payload, include_created_at=include_created_at)
    return digest


def _decode_payload(raw: Any) -> dict[str, Any]:
    """Return the receipt payload as a dict, whichever driver produced it.

    `payload` is a JSONB column. Postgres decodes it to a dict on the way out;
    SQLite has no JSON type and hands back the stored text. Calling json.loads
    unconditionally therefore worked on SQLite and raised
    `TypeError: the JSON object must be str, bytes or bytearray, not dict` on
    Postgres -- which nothing noticed, because ReceiptGate only ever ran on
    SQLite despite being the one component whose correctness is about
    concurrent writes.
    """
    if isinstance(raw, (str, bytes, bytearray)):
        return json.loads(raw)
    return dict(raw)


def store_receipt(
    db,
    payload: dict[str, Any],
    tenant_id: str,
    *,
    on_commit: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """Append a receipt, and apply the governance mutation it implies.

    `on_commit` runs inside the same transaction as the INSERT. That is the
    atomicity the whole model rests on: a committed receipt and the custody
    state it produces are one write. If the projection mutation fails, the
    receipt is not stored either -- there is no state where the ledger says an
    obligation was accepted and custody says nobody holds it.
    """
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
        # Same transaction, deliberately. Receipt append and projection
        # mutation are one atomic act or neither happens.
        if on_commit is not None:
            on_commit(db)
        db.commit()
    except Exception:
        db.rollback()
        raise

    # structlog-style kwargs against a stdlib logger raise TypeError, and this
    # line sits *after* db.commit() and outside the try/except above. At INFO
    # level -- the normal production posture -- every first write therefore
    # committed durably and then returned "Failed to store receipt" to the
    # client. A client that responds by minting a different receipt for the
    # same obligation corrupts the ledger. Logging must never change the
    # protocol result after commit.
    logger.info(
        "receiptgate_v1_receipt_stored",
        extra={
            "receipt_id": receipt_id,
            "tenant_id": tenant_id,
            "task_id": record.get("task_id"),
            "phase": record.get("phase"),
            "recipient_ai": record.get("recipient_ai"),
            "caused_by_receipt_id": record.get("caused_by_receipt_id"),
        },
    )

    return {"receipt_id": receipt_id, "stored_at": stored_at, "tenant_id": tenant_id}


def put_receipt(
    db,
    payload: dict[str, Any],
    tenant_id: str,
    *,
    actor: Principal | None = None,
) -> dict[str, Any]:
    """Commit a proposed governance transition, or refuse it.

    The receipt is not a description of something that already happened. This
    call *is* the transition: if it commits, responsibility has moved; if it is
    refused, nothing has changed anywhere.

    `actor` is the authenticated principal. When absent the transition guards
    are skipped, which exists only so the pre-notary tests and internal replay
    paths keep working -- the MCP route always supplies one.
    """
    receipt_id = payload.get("receipt_id")
    if not receipt_id:
        raise ValueError("receipt_id is required")

    incoming_hash = _canonical_receipt_hash(payload)
    existing = get_receipt(db, tenant_id, receipt_id)
    if existing:
        existing_hash = _canonical_receipt_hash(existing)
        if existing_hash == incoming_hash:
            return {
                "receipt_id": receipt_id,
                "stored_at": existing.get("stored_at"),
                "tenant_id": tenant_id,
                "canonical_hash": incoming_hash,
                "idempotent_replay": True,
            }
        raise ReceiptConflictError(
            receipt_id=receipt_id,
            existing_hash=existing_hash,
            incoming_hash=incoming_hash,
        )

    # Evaluate before writing anything. Illegal transitions are refused with a
    # typed code and leave no trace.
    transition_name: str | None = None
    custody = None
    if actor is not None:
        transition_name, custody, _state = notary.evaluate(
            db, payload, actor=actor, tenant_id=tenant_id
        )

    def _project(session: Any) -> None:
        if transition_name is None:
            return
        notary.apply_projection(
            session,
            payload,
            transition=transition_name,
            custody=custody,
            actor=actor,
            tenant_id=tenant_id,
        )

    try:
        result = store_receipt(db, payload, tenant_id, on_commit=_project)
    except IntegrityError:
        existing = get_receipt(db, tenant_id, receipt_id)
        if existing:
            existing_hash = _canonical_receipt_hash(existing)
            if existing_hash == incoming_hash:
                return {
                    "receipt_id": receipt_id,
                    "stored_at": existing.get("stored_at"),
                    "tenant_id": tenant_id,
                    "canonical_hash": incoming_hash,
                    "idempotent_replay": True,
                }
            raise ReceiptConflictError(
                receipt_id=receipt_id,
                existing_hash=existing_hash,
                incoming_hash=incoming_hash,
            )
        # No receipt collision, so the IntegrityError came from the custody
        # projection: another actor committed acceptance of this obligation
        # first. The database decided, not a check-then-write in application
        # code, so exactly one custodian exists and this is the loser.
        if transition_name == "ACCEPT":
            raise notary.TransitionRejected(
                "OBLIGATION_ALREADY_ACCEPTED",
                f"obligation {payload.get('obligation_id')} already has a "
                f"custodian; exactly one acceptance can win",
            )
        raise

    result.update({"canonical_hash": incoming_hash, "idempotent_replay": False})
    return result


def list_inbox(db, tenant_id: str, recipient_ai: str, limit: int = 20) -> dict[str, Any]:
    """Open obligations this principal currently holds.

    A VIEW, derived from canonical custody state. Nothing pushes rows here.

    It used to select `accepted` receipts and exclude any whose *task_id* had a
    terminal receipt, which broke in both directions:

      - Fan-out. Two reviewers accepting one task_id both vanished from their
        inboxes the moment either completed, because the NOT EXISTS correlated
        on task_id and not on the obligation.
      - Escalation delivered nothing. Only `accepted` receipts were visible, so
        a transfer put the obligation in nobody's inbox: gone from the issuer's
        because escalate is terminal, absent from the target's because the
        escalate receipt is not phase='accepted'. The whole soft-push model had
        no reader.

    Reading custody fixes both. The current custodian is whoever holds it now,
    however they came to hold it, and the obligation stays visible until a
    committed transition closes or transfers it.
    """
    rows = db.execute(
        text(
            """
            SELECT c.obligation_id,
                   o.task_id,
                   c.state,
                   c.custody_deadline,
                   c.accepted_receipt_id AS receipt_id
              FROM custody_state c
              JOIN obligations o
                ON o.tenant_id = c.tenant_id
               AND o.obligation_id = c.obligation_id
             WHERE c.tenant_id = :tenant_id
               AND c.current_custodian = :recipient_ai
               AND c.state IN ('OPEN', 'OVERDUE')
             ORDER BY c.updated_at DESC
             LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "recipient_ai": recipient_ai, "limit": limit},
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
                payload = _decode_payload(row["payload"])
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
            payload = _decode_payload(row["payload"])
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
                payload = _decode_payload(row["payload"])
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
