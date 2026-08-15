"""ReceiptGate as notary: the governance invariants, asserted directly.

Every test here fails if the corresponding guard is removed. They assert the
Slice Zero thesis at the ledger boundary:

    No authoritative change in responsibility can exist without a committed
    receipt transition.

What that decomposes into, and what each class below pins:

  accept before complete       a completion for an obligation nobody opened is
                               refused, rather than stored and returned green
  single custody               two acceptances resolve to exactly one custodian,
                               decided by the database and not by timing
  custodian-only discharge     a principal cannot close somebody else's work
  single closure               a terminal obligation cannot be closed twice or
                               reopened
  obligation-scoped closure    a completion closes the obligation it names and
                               nothing else that shares a task_id
  receipt immutability         closing an obligation does not alter the receipt
                               that opened it
  deadline is not a transition wall-clock passage leaves the custodian in place
  rebuildable projection       custody state reconstructs from receipts alone
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from legivellum.authority import Principal
from sqlalchemy import text

from receiptgate import notary
from receiptgate.ledger_v1 import get_receipt, list_inbox, put_receipt
from receiptgate.notary import TransitionRejected

TENANT = "tenant-a"
SERVICE = Principal(id="svc:test", role="service", visibility=TENANT)
OBSERVER = Principal(id="agent:auditor", role="observer", visibility=TENANT)


def receipt(
    *,
    receipt_id: str,
    obligation_id: str,
    executor: str,
    task_id: str = "task-1",
    phase: str = "accepted",
    caused_by: str = "NA",
    escalation_to: str | None = None,
    tenant_id: str = TENANT,
    deadline: datetime | None = None,
):
    now = datetime.now(timezone.utc).isoformat()
    is_escalate = phase == "escalate"
    metadata = {}
    if deadline is not None:
        metadata["custody_deadline"] = deadline.isoformat()
    return {
        "schema_version": "1.0",
        "tenant_id": tenant_id,
        "receipt_id": receipt_id,
        "task_id": task_id,
        "obligation_id": obligation_id,
        "parent_task_id": "NA",
        "caused_by_receipt_id": caused_by,
        "dedupe_key": "NA",
        "attempt": 0,
        # The requester opens; the custodian discharges.
        "from_principal": "principal:requester" if phase == "accepted" else executor,
        "for_principal": executor,
        "source_system": "svc:test",
        "recipient_ai": escalation_to if is_escalate else executor,
        "trust_domain": "test",
        "phase": phase,
        "status": "success" if phase == "complete" else "NA",
        "realtime": False,
        "task_type": "test.task",
        "task_summary": "s",
        "task_body": "b",
        "inputs": {},
        "expected_outcome_kind": "response_text",
        "expected_artifact_mime": "NA",
        "outcome_kind": "response_text" if phase == "complete" else "NA",
        "outcome_text": "done" if phase == "complete" else "NA",
        "artifact_location": "NA",
        "artifact_pointer": "NA",
        "artifact_checksum": "NA",
        "artifact_size_bytes": 0,
        "artifact_mime": "NA",
        "escalation_class": "capability" if is_escalate else "NA",
        "escalation_reason": "cannot proceed" if is_escalate else "NA",
        "escalation_to": escalation_to or "NA",
        "retry_requested": False,
        "body": {},
        "created_at": now,
        "stored_at": None,
        "started_at": now,
        "completed_at": now if phase == "complete" else None,
        "read_at": None,
        "archived_at": None,
        "metadata": metadata,
    }


def accept(db, *, obligation_id, executor, task_id="task-1", rid=None, deadline=None):
    return put_receipt(
        db,
        receipt(
            receipt_id=rid or f"r-accept-{obligation_id}",
            obligation_id=obligation_id,
            executor=executor,
            task_id=task_id,
            deadline=deadline,
        ),
        TENANT,
        actor=SERVICE,
    )


class TestAcceptBeforeComplete:
    def test_complete_without_accept_is_refused(self, db_session):
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-c",
                    obligation_id="obl-never-opened",
                    executor="agent:a",
                    phase="complete",
                ),
                TENANT,
                actor=SERVICE,
            )
        assert exc.value.code == "COMPLETE_WITHOUT_ACCEPT"

    def test_escalate_without_accept_is_refused(self, db_session):
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-e",
                    obligation_id="obl-never-opened",
                    executor="agent:a",
                    phase="escalate",
                    escalation_to="agent:b",
                ),
                TENANT,
                actor=SERVICE,
            )
        assert exc.value.code == "ESCALATE_WITHOUT_ACCEPT"

    def test_receipt_without_obligation_id_is_refused(self, db_session):
        payload = receipt(receipt_id="r-x", obligation_id="obl-1", executor="agent:a")
        del payload["obligation_id"]
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(db_session, payload, TENANT, actor=SERVICE)
        assert exc.value.code == "OBLIGATION_ID_REQUIRED"


class TestSingleCustody:
    def test_second_acceptance_of_one_obligation_is_refused(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-accept-2",
                    obligation_id="obl-1",
                    executor="agent:b",
                ),
                TENANT,
                actor=SERVICE,
            )
        assert exc.value.code in {
            "OBLIGATION_ALREADY_ACCEPTED",
            "OBLIGATION_ALREADY_EXISTS",
        }

    def test_exactly_one_custodian_survives(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        try:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-accept-2", obligation_id="obl-1", executor="agent:b"
                ),
                TENANT,
                actor=SERVICE,
            )
        except TransitionRejected:
            pass
        row = notary.read_custody(db_session, TENANT, "obl-1")
        assert row is not None
        assert row.current_custodian == "agent:a"

    def test_exclusion_is_a_database_constraint(self, db_session):
        """Not a check-then-write.

        The guarantee has to survive two transactions interleaving between the
        read and the write, which application logic cannot promise. Assert the
        constraint exists rather than trusting the code path.
        """
        rows = db_session.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type = 'index'")
        ).mappings().all()
        names = {r["name"] for r in rows}
        assert "idx_custody_one_live_grant" in names, (
            "the partial unique index that enforces single custody is missing; "
            "exclusion would rest on check-then-write timing"
        )
        sql = next(r["sql"] for r in rows if r["name"] == "idx_custody_one_live_grant")
        assert "UNIQUE" in sql.upper()


class TestCustodianOnlyDischarge:
    def test_a_different_principal_cannot_complete(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-c",
                    obligation_id="obl-1",
                    executor="agent:intruder",
                    phase="complete",
                ),
                TENANT,
                actor=SERVICE,
            )
        assert exc.value.code == "ACTOR_NOT_CUSTODIAN"

    def test_an_observer_may_propose_nothing(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-c",
                    obligation_id="obl-1",
                    executor="agent:a",
                    phase="complete",
                ),
                TENANT,
                actor=OBSERVER,
            )
        assert exc.value.code == "ACTOR_NOT_PERMITTED"


class TestSingleClosure:
    def test_completing_twice_is_refused(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        put_receipt(
            db_session,
            receipt(
                receipt_id="r-c1",
                obligation_id="obl-1",
                executor="agent:a",
                phase="complete",
            ),
            TENANT,
            actor=SERVICE,
        )
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-c2",
                    obligation_id="obl-1",
                    executor="agent:a",
                    phase="complete",
                ),
                TENANT,
                actor=SERVICE,
            )
        assert exc.value.code == "OBLIGATION_ALREADY_TERMINATED"

    def test_a_terminal_obligation_cannot_be_reaccepted(self, db_session):
        """This case used to store and then vanish.

        A fresh `accepted` for a completed task was accepted by put_receipt,
        returned success, and was then suppressed by the inbox query. The
        supervisor believed work was assigned, the agent never saw it, and no
        error was raised anywhere.
        """
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        put_receipt(
            db_session,
            receipt(
                receipt_id="r-c1",
                obligation_id="obl-1",
                executor="agent:a",
                phase="complete",
            ),
            TENANT,
            actor=SERVICE,
        )
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-a2", obligation_id="obl-1", executor="agent:a"
                ),
                TENANT,
                actor=SERVICE,
            )
        assert exc.value.code == "OBLIGATION_ALREADY_TERMINATED"


class TestTransfer:
    def test_escalation_moves_custody_and_is_visible_to_the_receiver(self, db_session):
        """Escalation used to deliver nothing.

        Only `accepted` receipts were inbox-visible, so a transfer left the
        obligation gone from the issuer's inbox and absent from the target's.
        The soft-push model had no reader at all.
        """
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        put_receipt(
            db_session,
            receipt(
                receipt_id="r-e",
                obligation_id="obl-1",
                executor="agent:a",
                phase="escalate",
                escalation_to="agent:b",
            ),
            TENANT,
            actor=SERVICE,
        )
        row = notary.read_custody(db_session, TENANT, "obl-1")
        # Responsibility moved; it did not end. The obligation is still open,
        # held by the receiver.
        assert row.state == "OPEN"
        assert row.current_custodian == "agent:b"
        assert list_inbox(db_session, TENANT, "agent:a", limit=10)["count"] == 0
        assert list_inbox(db_session, TENANT, "agent:b", limit=10)["count"] == 1, (
            "the receiving custodian cannot see the obligation transferred to "
            "them; the soft-push has no reader"
        )

    def test_previous_custodian_cannot_complete_after_transfer(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        put_receipt(
            db_session,
            receipt(
                receipt_id="r-e",
                obligation_id="obl-1",
                executor="agent:a",
                phase="escalate",
                escalation_to="agent:b",
            ),
            TENANT,
            actor=SERVICE,
        )
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-c",
                    obligation_id="obl-1",
                    executor="agent:a",
                    phase="complete",
                ),
                TENANT,
                actor=SERVICE,
            )
        # Refused because they are no longer the custodian, not because the
        # obligation ended -- it is still open, owed by somebody else.
        assert exc.value.code == "ACTOR_NOT_CUSTODIAN"

    def test_routing_invariant_is_enforced(self, db_session):
        """recipient_ai must equal escalation_to.

        Not expressible in JSON Schema, so it has to hold here. A violation
        transfers responsibility to one principal and routes the evidence to
        another.
        """
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        payload = receipt(
            receipt_id="r-e",
            obligation_id="obl-1",
            executor="agent:a",
            phase="escalate",
            escalation_to="agent:b",
        )
        payload["recipient_ai"] = "agent:someone-else"
        with pytest.raises(TransitionRejected) as exc:
            put_receipt(db_session, payload, TENANT, actor=SERVICE)
        assert exc.value.code == "ROUTING_INVARIANT_VIOLATION"


class TestReceiptImmutability:
    def test_closing_does_not_alter_the_accepted_receipt(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a", rid="r-a")
        before = get_receipt(db_session, TENANT, "r-a")
        put_receipt(
            db_session,
            receipt(
                receipt_id="r-c",
                obligation_id="obl-1",
                executor="agent:a",
                phase="complete",
            ),
            TENANT,
            actor=SERVICE,
        )
        after = get_receipt(db_session, TENANT, "r-a")
        assert before == after, (
            "the accepted receipt changed when the obligation closed; current "
            "state must live in the projection, never in receipt history"
        )

    def test_receipt_count_only_grows(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        n1 = db_session.execute(text("SELECT COUNT(*) FROM receipts_v1")).scalar()
        put_receipt(
            db_session,
            receipt(
                receipt_id="r-c",
                obligation_id="obl-1",
                executor="agent:a",
                phase="complete",
            ),
            TENANT,
            actor=SERVICE,
        )
        n2 = db_session.execute(text("SELECT COUNT(*) FROM receipts_v1")).scalar()
        assert n2 == n1 + 1


class TestDeadlineIsNotATransition:
    def test_passing_the_deadline_leaves_the_custodian_in_place(self, db_session):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        accept(db_session, obligation_id="obl-1", executor="agent:a", deadline=past)

        row = notary.read_custody(db_session, TENANT, "obl-1")
        assert row.current_custodian == "agent:a", "custody changed by itself"
        assert notary.effective_state(row) == "OVERDUE"
        assert row.state == "OPEN", (
            "the stored state was mutated by time passing; OVERDUE must be "
            "derived, or a background job is performing governance"
        )

    def test_another_worker_cannot_accept_an_overdue_obligation(self, db_session):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        accept(db_session, obligation_id="obl-1", executor="agent:a", deadline=past)
        with pytest.raises(TransitionRejected):
            put_receipt(
                db_session,
                receipt(
                    receipt_id="r-a2", obligation_id="obl-1", executor="agent:b"
                ),
                TENANT,
                actor=SERVICE,
            )

    def test_an_open_obligation_always_has_a_deadline(self, db_session):
        accept(db_session, obligation_id="obl-1", executor="agent:a")
        row = notary.read_custody(db_session, TENANT, "obl-1")
        assert row.custody_deadline is not None, (
            "custody with no deadline can never become recoverable, so it "
            "would be owed forever with no legal path to reassignment"
        )


class TestProjectionIsRebuildable:
    def test_rebuild_reproduces_the_live_projection(self, db_session):
        """The projection is derivable, not a second narrative."""
        accept(db_session, obligation_id="obl-1", executor="agent:a", task_id="t1")
        accept(db_session, obligation_id="obl-2", executor="agent:b", task_id="t1")
        put_receipt(
            db_session,
            receipt(
                receipt_id="r-c1",
                obligation_id="obl-1",
                executor="agent:a",
                task_id="t1",
                phase="complete",
            ),
            TENANT,
            actor=SERVICE,
        )

        live = {
            o: (notary.read_custody(db_session, TENANT, o).state,
                notary.read_custody(db_session, TENANT, o).current_custodian)
            for o in ("obl-1", "obl-2")
        }

        stats = notary.rebuild_projection(db_session, TENANT)
        assert stats["applied"] >= 3

        rebuilt = {
            o: (notary.read_custody(db_session, TENANT, o).state,
                notary.read_custody(db_session, TENANT, o).current_custodian)
            for o in ("obl-1", "obl-2")
        }
        assert rebuilt == live, (
            "rebuilding from the immutable ledger produced different custody "
            "than the live projection; the ledger is authoritative and the two "
            "must agree"
        )
