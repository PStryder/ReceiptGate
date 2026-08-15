"""ReceiptGate as notary: validate a proposed transition, or commit it.

This is the module that makes the architectural claim true. A responsibility
transition is not something that happens and is then described by a receipt --
the committed receipt *is* the transition. Nothing here decides what work should
occur, selects a worker, executes anything, or schedules anything. It evaluates
whether a proposed governance transition is legal and commits it atomically.

The shape:

    propose transition
          |
    schema validation            canonical receipt, already the case
    state machine                 transitions.v1.json -- legal from here?
    authority                     authority.v1.json  -- may this actor?
          |
    ONE transaction:
        append receipt (immutable)
        mutate custody projection
          |
    committed -> the transition is now authoritative

Two things it deliberately does not do:

- It never UPDATEs or DELETEs a receipt. Closure and transfer mutate the
  projection; receipt history is append-only truth.
- It never resolves custody exclusion by reading current state and writing if
  empty. Two concurrent acceptances both read empty. The database decides, via
  the partial unique index in schema/006.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from legivellum.authority import (
    NotPermitted,
    Principal,
    check_may_propose,
    resolve_transition_actor,
)
from legivellum.transitions import (
    IllegalTransition,
    check_transition,
    get_transition,
    transition_for_phase,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

# How long a custodian holds an obligation when the proposer does not say.
# There is no valid state in which custody exists with no deadline, so a
# default is required rather than optional.
DEFAULT_CUSTODY_SECONDS = 900

# Absence of a custody row is the NONE state.
STATE_NONE = "NONE"


class TransitionRejected(Exception):
    """A proposed transition is illegal. Carries the typed protocol code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CustodyRow:
    state: str
    current_custodian: str | None
    custody_deadline: datetime | None
    accepted_receipt_id: str
    version: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def read_custody(db, tenant_id: str, obligation_id: str) -> CustodyRow | None:
    """Read current custody. Returns None for an obligation that does not exist."""
    row = db.execute(
        text(
            """
            SELECT state, current_custodian, custody_deadline,
                   accepted_receipt_id, version
            FROM custody_state
            WHERE tenant_id = :tenant_id AND obligation_id = :obligation_id
            """
        ),
        {"tenant_id": tenant_id, "obligation_id": obligation_id},
    ).mappings().first()
    if row is None:
        return None
    return CustodyRow(
        state=row["state"],
        current_custodian=row["current_custodian"],
        custody_deadline=_as_datetime(row["custody_deadline"]),
        accepted_receipt_id=row["accepted_receipt_id"],
        version=row["version"],
    )


def effective_state(custody: CustodyRow | None, *, now: datetime | None = None) -> str:
    """The state the transition model should evaluate against.

    OVERDUE is derived from the deadline rather than written by a scheduled job,
    which is the point: reaching a deadline must not itself be a transition. The
    custodian is unchanged, the obligation is still owed, and it merely becomes
    eligible for a notarized RECOVER. No background process mutates custody, so
    a ReceiptGate outage cannot silently reassign anything.
    """
    if custody is None:
        return STATE_NONE
    if custody.state != "OPEN":
        return custody.state
    deadline = custody.custody_deadline
    if deadline is None:
        return custody.state
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return "OVERDUE" if (now or _utc_now()) >= deadline else "OPEN"


def resolve_transition(payload: dict[str, Any], current_state: str) -> str:
    """Which transition this receipt proposes, given where the obligation is.

    `escalate` is two different transitions depending on the state it starts
    from -- ESCALATE by the custodian, RECOVER by a third party reclaiming an
    abandoned obligation -- so this is a lookup against the model, never a match
    on the phase string.
    """
    phase = payload.get("phase")
    try:
        return transition_for_phase(str(phase), from_state=current_state).name
    except IllegalTransition as exc:
        raise TransitionRejected(exc.code, exc.message) from exc


def evaluate(
    db,
    payload: dict[str, Any],
    *,
    actor: Principal,
    tenant_id: str,
) -> tuple[str, CustodyRow | None, str]:
    """Decide whether the proposed transition is legal.

    Returns (transition_name, current_custody, current_state). Raises
    TransitionRejected with a typed code otherwise. No writes.
    """
    obligation_id = payload.get("obligation_id")
    if not obligation_id:
        raise TransitionRejected(
            "OBLIGATION_ID_REQUIRED",
            "receipt carries no obligation_id; an obligation with no identity "
            "can only be closed by matching on task_id, which closes obligations "
            "it does not name",
        )

    custody = read_custody(db, tenant_id, str(obligation_id))
    state = effective_state(custody)
    name = resolve_transition(payload, state)

    # Role: may this kind of actor propose this at all?
    try:
        check_may_propose(actor, name)
    except NotPermitted as exc:
        raise TransitionRejected(exc.code, exc.message) from exc

    # Who is actually performing this transition. A service proposes on behalf
    # of the principal it coordinates -- AsyncGate proposes ACCEPT for a
    # claiming worker -- so the custodian check runs against that principal,
    # not against the emitting service. A worker role cannot claim to act for
    # anyone else, which keeps this a delegation rather than a bypass.
    transition_actor = resolve_transition_actor(actor, payload)
    is_custodian = bool(custody and custody.current_custodian == transition_actor)
    try:
        check_transition(
            name,
            current_state=state,
            actor_is_custodian=is_custodian,
            obligation_exists=custody is not None,
        )
    except IllegalTransition as exc:
        raise TransitionRejected(exc.code, exc.message) from exc

    # The custodian requirement is enforced by check_transition above, because
    # COMPLETE and ESCALATE declare `actor_is_current_custodian` among their
    # guards in transitions.v1.json. There is deliberately no second check here:
    # a redundant copy drifts from the model, and the model is the thing that is
    # supposed to be authoritative. RECOVER is exempt by construction -- it does
    # not declare that guard, because it is precisely the transition a
    # non-custodian makes to reclaim an abandoned obligation.

    if name in {"ESCALATE", "RECOVER"}:
        _check_routing_invariant(payload)

    return name, custody, state


def _check_routing_invariant(payload: dict[str, Any]) -> None:
    """recipient_ai MUST equal escalation_to.

    Cannot be expressed in JSON Schema, so the canonical rules require it in
    application code. An escalation that violates it transfers responsibility
    to one principal while landing in another's inbox.
    """
    recipient = payload.get("recipient_ai")
    target = payload.get("escalation_to")
    if not target or target == "NA":
        raise TransitionRejected(
            "ROUTING_INVARIANT_VIOLATION",
            "escalate receipt names no escalation_to; responsibility would "
            "transfer to nobody",
        )
    if recipient != target:
        raise TransitionRejected(
            "ROUTING_INVARIANT_VIOLATION",
            f"recipient_ai {recipient!r} must equal escalation_to {target!r}",
        )


def apply_projection(
    db,
    payload: dict[str, Any],
    *,
    transition: str,
    custody: CustodyRow | None,
    actor: Principal,
    tenant_id: str,
) -> None:
    """Mutate governance state for a committed transition.

    Called inside the same transaction as the receipt append. Never touches the
    receipt table.
    """
    obligation_id = str(payload["obligation_id"])
    receipt_id = str(payload["receipt_id"])

    if transition == "ACCEPT":
        _open_obligation(db, payload, actor=actor, tenant_id=tenant_id)
        return

    spec = get_transition(transition)
    to_state = spec.to_state

    if to_state == "OPEN":
        # Custody transfer. The obligation stays open -- responsibility moved,
        # it did not end -- so the receiver holds it and appears in their view
        # immediately, and the previous custodian can no longer discharge it.
        new_custodian = payload.get("escalation_to")
        result = db.execute(
            text(
                """
                UPDATE custody_state
                   SET current_custodian = :custodian,
                       custody_deadline = :deadline,
                       accepted_receipt_id = :receipt_id,
                       state = 'OPEN',
                       version = version + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE tenant_id = :tenant_id
                   AND obligation_id = :obligation_id
                   AND version = :version
                   AND state IN ('OPEN', 'OVERDUE')
                """
            ),
            {
                "custodian": str(new_custodian),
                # A transferred obligation gets a fresh deadline: the new
                # custodian inheriting an already-expired one would be overdue
                # the instant they received it.
                "deadline": _utc_now() + timedelta(seconds=DEFAULT_CUSTODY_SECONDS),
                "receipt_id": receipt_id,
                "tenant_id": tenant_id,
                "obligation_id": obligation_id,
                "version": custody.version if custody else -1,
            },
        )
    else:
        # Closure. Conditional on version and state so a concurrent transition
        # loses rather than both landing; rowcount 0 means somebody moved first.
        result = db.execute(
            text(
                """
                UPDATE custody_state
                   SET state = :to_state,
                       current_custodian = NULL,
                       custody_deadline = NULL,
                       closed_by_receipt_id = :receipt_id,
                       version = version + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE tenant_id = :tenant_id
                   AND obligation_id = :obligation_id
                   AND version = :version
                   AND state IN ('OPEN', 'OVERDUE')
                """
            ),
            {
                "to_state": to_state,
                "receipt_id": receipt_id,
                "tenant_id": tenant_id,
                "obligation_id": obligation_id,
                "version": custody.version if custody else -1,
            },
        )

    if result.rowcount == 0:
        raise TransitionRejected(
            "OBLIGATION_ALREADY_TERMINATED",
            f"obligation {obligation_id} was resolved concurrently by another "
            f"transition; this one is refused rather than overwriting it",
        )


def _open_obligation(
    db, payload: dict[str, Any], *, actor: Principal, tenant_id: str
) -> None:
    """Create the obligation and its custody grant.

    The INSERT into custody_state is what enforces single custody. Two
    concurrent acceptances race here and the database picks one; the loser gets
    an IntegrityError which the caller returns as a typed conflict.
    """
    obligation_id = str(payload["obligation_id"])
    receipt_id = str(payload["receipt_id"])
    deadline = _custody_deadline(payload)

    db.execute(
        text(
            """
            INSERT INTO obligations (
                tenant_id, obligation_id, task_id,
                authorizer_principal, beneficiary_principal, visibility_principal,
                opened_by_receipt_id
            ) VALUES (
                :tenant_id, :obligation_id, :task_id,
                :authorizer, :beneficiary, :visibility,
                :receipt_id
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "obligation_id": obligation_id,
            "task_id": str(payload.get("task_id")),
            # All three derived from the receipt, so this table rebuilds from
            # the ledger. visibility comes from the authenticated principal,
            # never from a caller-supplied string.
            "authorizer": str(payload.get("from_principal")),
            "beneficiary": str(payload.get("for_principal")),
            "visibility": actor.visibility,
            "receipt_id": receipt_id,
        },
    )

    db.execute(
        text(
            """
            INSERT INTO custody_state (
                tenant_id, obligation_id, state, current_custodian,
                custody_deadline, accepted_receipt_id
            ) VALUES (
                :tenant_id, :obligation_id, 'OPEN', :custodian,
                :deadline, :receipt_id
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "obligation_id": obligation_id,
            # The custodian is `for_principal`: the canonical schema's
            # "Intended executor (taskee)", i.e. the party that owes the work.
            # NOT recipient_ai, which the schema defines as the inbox owner for
            # a single receipt -- routing, not responsibility. They coincide on
            # an ACCEPT and diverge on a completion reported back to the
            # requester, so conflating them refuses every completion.
            "custodian": str(payload.get("for_principal")),
            "deadline": deadline,
            "receipt_id": receipt_id,
        },
    )


def _custody_deadline(payload: dict[str, Any]) -> datetime:
    """Every accepted obligation gets a deadline.

    Taken from the receipt's metadata when supplied, otherwise defaulted. There
    is no valid state in which custody exists with no deadline -- an obligation
    nobody is required to finish by any time cannot become recoverable, so it
    would be owed forever with no legal path to reassignment.
    """
    metadata = payload.get("metadata") or {}
    raw = metadata.get("custody_deadline")
    parsed = _as_datetime(raw) if raw else None
    if parsed is not None:
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return _utc_now() + timedelta(seconds=DEFAULT_CUSTODY_SECONDS)


def rebuild_projection(db, tenant_id: str) -> dict[str, int]:
    """Rebuild governance state from the immutable receipt ledger.

    The projection is not a second global narrative: it is derivable, and when
    it disagrees with the ledger the ledger wins and this repairs it. Replays
    receipts in stored order, applying the same transitions the write path
    applies.
    """
    rows = db.execute(
        text(
            """
            SELECT payload FROM receipts_v1
            WHERE tenant_id = :tenant_id
            ORDER BY stored_at, receipt_id
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()

    db.execute(
        text("DELETE FROM custody_state WHERE tenant_id = :t"), {"t": tenant_id}
    )
    db.execute(
        text("DELETE FROM obligations WHERE tenant_id = :t"), {"t": tenant_id}
    )

    applied = 0
    skipped = 0
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        obligation_id = payload.get("obligation_id")
        if not obligation_id:
            skipped += 1
            continue

        custody = read_custody(db, tenant_id, str(obligation_id))
        state = effective_state(custody)
        try:
            name = transition_for_phase(str(payload.get("phase")), from_state=state).name
        except IllegalTransition:
            skipped += 1
            continue

        # Replay reconstructs from the receipt's own principals rather than an
        # authenticated caller, which is why visibility is read back from the
        # receipt's tenant.
        replay_actor = Principal(
            id=str(payload.get("recipient_ai")),
            role="service",
            visibility=str(payload.get("tenant_id") or tenant_id),
        )
        try:
            apply_projection(
                db,
                payload,
                transition=name,
                custody=custody,
                actor=replay_actor,
                tenant_id=tenant_id,
            )
            applied += 1
        except (TransitionRejected, IntegrityError):
            skipped += 1

    return {"applied": applied, "skipped": skipped, "receipts": len(rows)}
