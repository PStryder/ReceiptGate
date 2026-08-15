-- Governance state: obligation identity and current custody.
--
-- Receipts stay append-only and are never updated to express closure. Current
-- state lives here and mutates, in the same transaction as the receipt append
-- that implies it. Everything in these tables is reconstructible from the
-- immutable ledger; if the two disagree, the ledger is authoritative and this
-- is repaired.
--
-- The load-bearing property is the partial unique index at the bottom. Custody
-- exclusion cannot be "read the current state, and write if it is empty" --
-- two concurrent acceptances both read empty and both write. The database has
-- to make a second live custody grant unrepresentable.

BEGIN;

-- One row per governed responsibility. Immutable after creation: an
-- obligation's authorizer, beneficiary and visibility are fixed at accept.
CREATE TABLE IF NOT EXISTS obligations (
  tenant_id             TEXT NOT NULL,
  obligation_id         TEXT NOT NULL,

  -- Grouping key. Several obligations may share one task_id; that is the whole
  -- reason obligation_id exists.
  task_id               TEXT NOT NULL,

  -- The three obligation-scoped identities. Derived from the ACCEPT receipt,
  -- so this table is rebuildable from the ledger.
  authorizer_principal  TEXT NOT NULL,   -- receipt.from_principal
  beneficiary_principal TEXT NOT NULL,   -- receipt.for_principal
  visibility_principal  TEXT NOT NULL,   -- authenticated tenant at commit

  opened_by_receipt_id  TEXT NOT NULL,
  opened_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (tenant_id, obligation_id)
);

CREATE INDEX IF NOT EXISTS idx_obligations_task
  ON obligations (tenant_id, task_id);

CREATE INDEX IF NOT EXISTS idx_obligations_visibility
  ON obligations (tenant_id, visibility_principal);


-- Current state. This is the table that mutates.
CREATE TABLE IF NOT EXISTS custody_state (
  tenant_id            TEXT NOT NULL,
  obligation_id        TEXT NOT NULL,

  -- OPEN | OVERDUE | CLOSED | TRANSFERRED. Mirrors transitions.v1.json;
  -- NONE is the absence of a row rather than a value.
  state                TEXT NOT NULL
    CHECK (state IN ('OPEN', 'OVERDUE', 'CLOSED', 'TRANSFERRED')),

  -- Who owes it right now. NULL once terminal.
  current_custodian    TEXT NULL,

  -- Every obligation that is open has a deadline: there is no valid state in
  -- which custody exists with no deadline.
  custody_deadline     TIMESTAMPTZ NULL,

  accepted_receipt_id  TEXT NOT NULL,
  closed_by_receipt_id TEXT NULL,
  transferred_to       TEXT NULL,

  -- Optimistic-concurrency counter for transitions that read then write.
  version              INTEGER NOT NULL DEFAULT 1,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (tenant_id, obligation_id),
  FOREIGN KEY (tenant_id, obligation_id)
    REFERENCES obligations (tenant_id, obligation_id),

  -- An open obligation must have both a custodian and a deadline; a terminal
  -- one must have neither pending. Stated as a constraint so "custody with no
  -- deadline" cannot exist even transiently.
  CONSTRAINT custody_open_has_custodian_and_deadline CHECK (
    (state IN ('OPEN', 'OVERDUE')
       AND current_custodian IS NOT NULL
       AND custody_deadline IS NOT NULL)
    OR
    (state IN ('CLOSED', 'TRANSFERRED')
       AND closed_by_receipt_id IS NOT NULL)
  )
);

-- THE mutual-exclusion guarantee.
--
-- At most one live custody grant per obligation. Because the primary key is
-- already (tenant_id, obligation_id) this is implied for the projection, but
-- the partial index states the property being relied on and keeps it true if
-- the table is ever widened to keep custody history in-place.
--
-- Two concurrent ACCEPTs therefore resolve to exactly one committed custodian:
-- the loser's INSERT violates this and is returned as a typed conflict, rather
-- than both passing a check-then-write and producing double custody.
CREATE UNIQUE INDEX IF NOT EXISTS idx_custody_one_live_grant
  ON custody_state (tenant_id, obligation_id)
  WHERE state IN ('OPEN', 'OVERDUE');

CREATE INDEX IF NOT EXISTS idx_custody_custodian
  ON custody_state (tenant_id, current_custodian, state);

CREATE INDEX IF NOT EXISTS idx_custody_deadline
  ON custody_state (tenant_id, state, custody_deadline);

COMMIT;
