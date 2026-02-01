"""Receipt persistence and validation logic."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from receiptgate.config import settings
from receiptgate.errors import ReceiptGateError, body_too_large, conflict_error, validation_error
from receiptgate.models import (
    ReceiptChainResponse,
    ReceiptCreateRequest,
    ReceiptInboxItem,
    ReceiptInboxResponse,
    ReceiptPutResponse,
    ReceiptRecord,
    ReceiptSearchRequest,
    ReceiptSearchResponse,
    ReceiptStatsResponse,
)
from receiptgate.utils import canonical_hash, json_size_bytes, normalize_datetime, utc_now

logger = logging.getLogger(__name__)


def _dump_model(value: Any, *, by_alias: bool = True) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True, by_alias=by_alias)
    if isinstance(value, list):
        return [_dump_model(item, by_alias=by_alias) for item in value]
    return value


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _receipt_payload(receipt: ReceiptCreateRequest) -> dict[str, Any]:
    return receipt.model_dump(mode="json", exclude_none=True, exclude_unset=True, by_alias=True)


def _compute_canonical(receipt: ReceiptCreateRequest) -> tuple[str, str]:
    payload = _receipt_payload(receipt)
    include_created_at = receipt.created_at is not None
    return canonical_hash(payload, include_created_at=include_created_at)


def _body_size_check(receipt: ReceiptCreateRequest) -> None:
    body_payload = _dump_model(receipt.body)
    size = json_size_bytes(body_payload)
    if size > settings.receipt_body_max_bytes:
        raise body_too_large(settings.receipt_body_max_bytes, size)


def _artifact_refs_check(receipt: ReceiptCreateRequest) -> None:
    if not receipt.artifact_refs:
        return
    for ref in receipt.artifact_refs:
        if ref.kind in {"binary", "dataset"} and not ref.digest:
            raise ReceiptGateError(
                status_code=422,
                code="ARTIFACT_REF_INVALID",
                message="artifact_ref.digest required for binary/dataset kinds",
                details={"artifact_id": ref.artifact_id, "uri": ref.uri, "kind": ref.kind},
            )


def _ensure_cause_valid(db, receipt: ReceiptCreateRequest) -> None:
    if not receipt.caused_by_receipt_id:
        return
    if receipt.caused_by_receipt_id == receipt.receipt_id:
        raise validation_error("caused_by_receipt_id cannot equal receipt_id")
    if settings.enforce_cause_exists and not _get_receipt_row(db, receipt.caused_by_receipt_id):
        raise ReceiptGateError(
            status_code=422,
            code="CAUSE_NOT_FOUND",
            message="caused_by_receipt_id does not exist",
            details={"caused_by_receipt_id": receipt.caused_by_receipt_id},
        )


def _terminal_for_obligation(db, obligation_id: str) -> Optional[dict[str, Any]]:
    query = text(
        """
        SELECT receipt_id, phase
        FROM receipts
        WHERE obligation_id = :obligation_id
          AND phase IN ('complete', 'escalate', 'cancel')
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    row = db.execute(query, {"obligation_id": obligation_id}).mappings().first()
    return dict(row) if row else None


def _accept_exists_for_obligation(db, obligation_id: str) -> bool:
    query = text(
        """
        SELECT 1 FROM receipts
        WHERE obligation_id = :obligation_id AND phase = 'accepted'
        LIMIT 1
        """
    )
    return db.execute(query, {"obligation_id": obligation_id}).first() is not None


def _escalation_child_exists(db, child_obligation_id: str) -> Optional[str]:
    if settings.db_backend == "postgres":
        query = text(
            """
            SELECT receipt_id
            FROM receipts
            WHERE phase = 'escalate'
              AND (body->'escalation'->>'child_obligation_id') = :child_id
            LIMIT 1
            """
        )
        row = db.execute(query, {"child_id": child_obligation_id}).mappings().first()
        if row:
            return row["receipt_id"]

    if settings.db_backend == "sqlite":
        try:
            query = text(
                """
                SELECT receipt_id
                FROM receipts
                WHERE phase = 'escalate'
                  AND json_extract(body, '$.escalation.child_obligation_id') = :child_id
                LIMIT 1
                """
            )
            row = db.execute(query, {"child_id": child_obligation_id}).mappings().first()
            if row:
                return row["receipt_id"]
        except Exception:
            pass

    rows = db.execute(
        text("SELECT receipt_id, body FROM receipts WHERE phase = 'escalate'")
    ).mappings()
    for row in rows:
        body = _parse_json(row["body"]) or {}
        child = (body.get("escalation") or {}).get("child_obligation_id")
        if child == child_obligation_id:
            return row["receipt_id"]
    return None


def _open_event_exists(db, obligation_id: str) -> bool:
    if _accept_exists_for_obligation(db, obligation_id):
        return True
    return _escalation_child_exists(db, obligation_id) is not None


def _get_receipt_row(db, receipt_id: str) -> Optional[dict[str, Any]]:
    query = text("SELECT * FROM receipts WHERE receipt_id = :receipt_id")
    row = db.execute(query, {"receipt_id": receipt_id}).mappings().first()
    return dict(row) if row else None


def _receipt_row_to_model(row: dict[str, Any]) -> ReceiptRecord:
    payload = {
        "receipt_id": row["receipt_id"],
        "phase": row["phase"],
        "obligation_id": row["obligation_id"],
        "caused_by_receipt_id": row.get("caused_by_receipt_id"),
        "created_by": row["created_by"],
        "recipient": row["recipient"],
        "principal": row.get("principal"),
        "task_ref": _parse_json(row.get("task_ref")),
        "plan_ref": _parse_json(row.get("plan_ref")),
        "artifact_refs": _parse_json(row.get("artifact_refs")),
        "body": _parse_json(row.get("body")) or {},
        "created_at": row.get("created_at"),
        "canonical_hash": row.get("canonical_hash"),
    }
    return ReceiptRecord.model_validate(payload)


def _validate_phase_invariants(db, receipt: ReceiptCreateRequest) -> None:
    if receipt.phase == "accepted":
        terminal = _terminal_for_obligation(db, receipt.obligation_id)
        if terminal:
            raise conflict_error(
                "OBLIGATION_ALREADY_TERMINATED",
                "Cannot accept obligation because it is already terminated",
                {
                    "obligation_id": receipt.obligation_id,
                    "terminal_receipt_id": terminal["receipt_id"],
                    "terminal_phase": terminal["phase"],
                },
            )
        return

    if receipt.phase == "complete":
        if not _open_event_exists(db, receipt.obligation_id):
            raise conflict_error(
                "COMPLETE_WITHOUT_ACCEPT",
                "Cannot complete obligation without an open event",
                {"obligation_id": receipt.obligation_id},
            )
        terminal = _terminal_for_obligation(db, receipt.obligation_id)
        if terminal:
            raise conflict_error(
                "OBLIGATION_ALREADY_TERMINATED",
                "Cannot complete obligation because it is already terminated",
                {
                    "obligation_id": receipt.obligation_id,
                    "terminal_receipt_id": terminal["receipt_id"],
                    "terminal_phase": terminal["phase"],
                },
            )
        return

    if receipt.phase == "cancel":
        if not _open_event_exists(db, receipt.obligation_id):
            raise conflict_error(
                "CANCEL_WITHOUT_ACCEPT",
                "Cannot cancel obligation without an open event",
                {"obligation_id": receipt.obligation_id},
            )
        terminal = _terminal_for_obligation(db, receipt.obligation_id)
        if terminal:
            raise conflict_error(
                "OBLIGATION_ALREADY_TERMINATED",
                "Cannot cancel obligation because it is already terminated",
                {
                    "obligation_id": receipt.obligation_id,
                    "terminal_receipt_id": terminal["receipt_id"],
                    "terminal_phase": terminal["phase"],
                },
            )
        return

    if receipt.phase == "escalate":
        escalation = receipt.body.escalation
        if escalation is None:
            raise validation_error("escalate requires body.escalation")

        if receipt.created_by != receipt.recipient:
            raise validation_error("escalate must be minted by receiver (created_by == recipient)")
        if receipt.recipient != escalation.to:
            raise validation_error("escalate recipient must match escalation.to")
        if receipt.obligation_id != escalation.parent_obligation_id:
            raise validation_error(
                "escalate receipt.obligation_id must equal escalation.parent_obligation_id"
            )

        parent = _get_receipt_row(db, escalation.parent_receipt_id)
        if not parent or parent.get("phase") != "accepted":
            raise conflict_error(
                "ESCALATE_PARENT_INVALID",
                "Parent receipt must exist and be accepted",
                {"parent_receipt_id": escalation.parent_receipt_id},
            )
        if parent.get("obligation_id") != escalation.parent_obligation_id:
            raise conflict_error(
                "ESCALATE_PARENT_INVALID",
                "Parent obligation mismatch",
                {
                    "parent_receipt_id": escalation.parent_receipt_id,
                    "parent_obligation_id": escalation.parent_obligation_id,
                },
            )

        terminal = _terminal_for_obligation(db, escalation.parent_obligation_id)
        if terminal:
            raise conflict_error(
                "OBLIGATION_ALREADY_TERMINATED",
                "Cannot escalate obligation because it is already terminated",
                {
                    "obligation_id": escalation.parent_obligation_id,
                    "terminal_receipt_id": terminal["receipt_id"],
                    "terminal_phase": terminal["phase"],
                },
            )

        if _get_receipt_row(db, escalation.child_obligation_id):
            raise conflict_error(
                "CHILD_OBLIGATION_ALREADY_EXISTS",
                "Child obligation already has receipts",
                {"child_obligation_id": escalation.child_obligation_id},
            )
        existing_child = _escalation_child_exists(db, escalation.child_obligation_id)
        if existing_child:
            raise conflict_error(
                "CHILD_OBLIGATION_ALREADY_EXISTS",
                "Child obligation already opened by escalation",
                {
                    "child_obligation_id": escalation.child_obligation_id,
                    "existing_receipt_id": existing_child,
                },
            )


def _insert_receipt(db, receipt: ReceiptCreateRequest, canonical_hash_value: str, created_at: datetime) -> None:
    payload_body = _dump_model(receipt.body)
    payload_task_ref = _dump_model(receipt.task_ref)
    payload_plan_ref = _dump_model(receipt.plan_ref)
    payload_artifacts = _dump_model(receipt.artifact_refs)

    json_cast = "::jsonb" if settings.db_backend == "postgres" else ""

    insert_query = text(
        f"""
        INSERT INTO receipts (
            uuid,
            receipt_id,
            canonical_hash,
            phase,
            obligation_id,
            caused_by_receipt_id,
            created_by,
            recipient,
            principal,
            task_id,
            task_ref,
            plan_id,
            plan_ref,
            artifact_refs,
            body,
            created_at
        ) VALUES (
            :uuid,
            :receipt_id,
            :canonical_hash,
            :phase,
            :obligation_id,
            :caused_by_receipt_id,
            :created_by,
            :recipient,
            :principal,
            :task_id,
            :task_ref{json_cast},
            :plan_id,
            :plan_ref{json_cast},
            :artifact_refs{json_cast},
            :body{json_cast},
            :created_at
        )
        """
    )

    task_id = receipt.task_ref.task_id if receipt.task_ref else None
    plan_id = receipt.plan_ref.plan_id if receipt.plan_ref else None

    db.execute(
        insert_query,
        {
            "uuid": str(uuid.uuid4()),
            "receipt_id": receipt.receipt_id,
            "canonical_hash": canonical_hash_value,
            "phase": receipt.phase,
            "obligation_id": receipt.obligation_id,
            "caused_by_receipt_id": receipt.caused_by_receipt_id,
            "created_by": receipt.created_by,
            "recipient": receipt.recipient,
            "principal": receipt.principal,
            "task_id": task_id,
            "task_ref": json.dumps(payload_task_ref) if payload_task_ref is not None else None,
            "plan_id": plan_id,
            "plan_ref": json.dumps(payload_plan_ref) if payload_plan_ref is not None else None,
            "artifact_refs": json.dumps(payload_artifacts) if payload_artifacts is not None else None,
            "body": json.dumps(payload_body) if payload_body is not None else None,
            "created_at": created_at,
        },
    )


def put_receipt(db, receipt: ReceiptCreateRequest) -> tuple[ReceiptPutResponse, int]:
    _, canonical_hash_value = _compute_canonical(receipt)

    existing = _get_receipt_row(db, receipt.receipt_id)
    if existing:
        if existing.get("canonical_hash") == canonical_hash_value:
            response = ReceiptPutResponse(
                receipt_id=receipt.receipt_id,
                canonical_hash=canonical_hash_value,
                created_at=existing.get("created_at"),
                idempotent_replay=True,
            )
            return response, 200
        raise conflict_error(
            "RECEIPT_ID_COLLISION",
            "receipt_id collision with different canonical hash",
            {
                "receipt_id": receipt.receipt_id,
                "existing_hash": existing.get("canonical_hash"),
                "incoming_hash": canonical_hash_value,
            },
        )

    _body_size_check(receipt)
    _artifact_refs_check(receipt)
    _ensure_cause_valid(db, receipt)
    _validate_phase_invariants(db, receipt)

    created_at = normalize_datetime(receipt.created_at) if receipt.created_at else utc_now()

    try:
        _insert_receipt(db, receipt, canonical_hash_value, created_at)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_receipt_row(db, receipt.receipt_id)
        if existing and existing.get("canonical_hash") == canonical_hash_value:
            response = ReceiptPutResponse(
                receipt_id=receipt.receipt_id,
                canonical_hash=canonical_hash_value,
                created_at=existing.get("created_at"),
                idempotent_replay=True,
            )
            return response, 200
        raise conflict_error(
            "RECEIPT_ID_COLLISION",
            "receipt_id collision during insert",
            {"receipt_id": receipt.receipt_id},
        )

    response = ReceiptPutResponse(
        receipt_id=receipt.receipt_id,
        canonical_hash=canonical_hash_value,
        created_at=created_at,
        idempotent_replay=False,
    )
    return response, 201


def get_receipt(db, receipt_id: str) -> Optional[ReceiptRecord]:
    row = _get_receipt_row(db, receipt_id)
    if not row:
        return None
    return _receipt_row_to_model(row)


def search_receipts(db, request: ReceiptSearchRequest) -> ReceiptSearchResponse:
    clauses: list[str] = []
    params: dict[str, Any] = {}

    def add_clause(field: str, value: Any):
        clauses.append(f"{field} = :{field}")
        params[field] = value

    if request.receipt_id:
        add_clause("receipt_id", request.receipt_id)
    if request.obligation_id:
        add_clause("obligation_id", request.obligation_id)
    if request.phase:
        add_clause("phase", request.phase)
    if request.recipient:
        add_clause("recipient", request.recipient)
    if request.created_by:
        add_clause("created_by", request.created_by)
    if request.principal:
        add_clause("principal", request.principal)
    if request.caused_by_receipt_id:
        add_clause("caused_by_receipt_id", request.caused_by_receipt_id)
    if request.task_id:
        add_clause("task_id", request.task_id)
    if request.plan_id:
        add_clause("plan_id", request.plan_id)
    if request.created_at_from:
        clauses.append("created_at >= :created_at_from")
        params["created_at_from"] = request.created_at_from
    if request.created_at_to:
        clauses.append("created_at <= :created_at_to")
        params["created_at_to"] = request.created_at_to

    if request.query:
        if settings.db_backend == "postgres":
            clauses.append("CAST(body AS TEXT) ILIKE :query")
        else:
            clauses.append("CAST(body AS TEXT) LIKE :query")
        params["query"] = f"%{request.query}%"

    where_sql = " AND ".join(clauses) if clauses else "1=1"

    limit = request.limit or settings.search_default_limit
    limit = min(limit, settings.search_max_limit)
    offset = request.offset or 0

    query = text(
        f"""
        SELECT * FROM receipts
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    params.update({"limit": limit, "offset": offset})
    rows = db.execute(query, params).mappings().all()
    receipts = [_receipt_row_to_model(dict(row)) for row in rows]

    count_query = text(f"SELECT COUNT(*) AS count FROM receipts WHERE {where_sql}")
    count = db.execute(count_query, params).mappings().first()["count"]

    return ReceiptSearchResponse(
        count=int(count),
        limit=limit,
        offset=offset,
        receipts=receipts,
    )


def chain_for_receipt(db, receipt_id: str) -> ReceiptChainResponse:
    chain: list[ReceiptRecord] = []
    truncated = False
    current_id = receipt_id
    visited: set[str] = set()

    while current_id:
        if current_id in visited:
            truncated = True
            break
        visited.add(current_id)
        row = _get_receipt_row(db, current_id)
        if not row:
            break
        chain.append(_receipt_row_to_model(row))
        current_id = row.get("caused_by_receipt_id")
        if len(chain) >= settings.receipt_chain_max_depth:
            truncated = True
            break

    chain.reverse()
    return ReceiptChainResponse(
        receipt_id=receipt_id,
        chain=chain,
        truncated=truncated,
    )


def inbox_for_recipient(db, recipient: str, limit: int) -> ReceiptInboxResponse:
    items: list[ReceiptInboxItem] = []
    seen_obligations: set[str] = set()

    accepted_query = text(
        """
        SELECT * FROM receipts
        WHERE phase = 'accepted' AND recipient = :recipient
        ORDER BY created_at DESC
        """
    )
    rows = db.execute(accepted_query, {"recipient": recipient}).mappings().all()
    for row in rows:
        obligation_id = row["obligation_id"]
        if obligation_id in seen_obligations:
            continue
        terminal = _terminal_for_obligation(db, obligation_id)
        if terminal:
            continue
        record = _receipt_row_to_model(dict(row))
        items.append(
            ReceiptInboxItem(
                obligation_id=obligation_id,
                opened_by_receipt_id=row["receipt_id"],
                opened_by_phase="accepted",
                receipt=record,
            )
        )
        seen_obligations.add(obligation_id)

    esc_rows = db.execute(
        text("SELECT * FROM receipts WHERE phase = 'escalate'")
    ).mappings().all()
    for row in esc_rows:
        body = _parse_json(row.get("body")) or {}
        escalation = body.get("escalation") or {}
        if escalation.get("to") != recipient:
            continue
        child_id = escalation.get("child_obligation_id")
        if not child_id or child_id in seen_obligations:
            continue
        terminal = _terminal_for_obligation(db, child_id)
        if terminal:
            continue
        record = _receipt_row_to_model(dict(row))
        items.append(
            ReceiptInboxItem(
                obligation_id=child_id,
                opened_by_receipt_id=row["receipt_id"],
                opened_by_phase="escalate",
                receipt=record,
                parent_obligation_id=escalation.get("parent_obligation_id"),
            )
        )
        seen_obligations.add(child_id)

    items = sorted(
        items,
        key=lambda item: item.receipt.created_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if limit > 0:
        items = items[:limit]

    return ReceiptInboxResponse(recipient=recipient, items=items)


def stats(db) -> ReceiptStatsResponse:
    total_row = db.execute(text("SELECT COUNT(*) AS count FROM receipts")).mappings().first()
    total = int(total_row["count"]) if total_row else 0

    phase_rows = db.execute(
        text("SELECT phase, COUNT(*) AS count FROM receipts GROUP BY phase")
    ).mappings()
    by_phase = {row["phase"]: int(row["count"]) for row in phase_rows}

    top_rows = db.execute(
        text(
            """
            SELECT recipient, COUNT(*) AS count
            FROM receipts
            GROUP BY recipient
            ORDER BY count DESC
            LIMIT 10
            """
        )
    ).mappings()
    top_recipients = [
        {"recipient": row["recipient"], "count": int(row["count"])}
        for row in top_rows
    ]

    return ReceiptStatsResponse(
        total_receipts=total,
        by_phase=by_phase,
        top_recipients=top_recipients,
    )
