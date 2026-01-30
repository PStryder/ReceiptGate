BEGIN;

CREATE TABLE IF NOT EXISTS receipts (
  uuid UUID PRIMARY KEY,
  receipt_id TEXT NOT NULL UNIQUE,
  canonical_hash TEXT NOT NULL,

  phase TEXT NOT NULL CHECK (phase IN ('accepted', 'complete', 'escalate', 'cancel')),

  obligation_id TEXT NOT NULL,
  caused_by_receipt_id TEXT NULL,

  created_by TEXT NOT NULL,
  recipient TEXT NOT NULL,
  principal TEXT NULL,

  task_id TEXT NULL,
  task_ref JSONB NULL,

  plan_id TEXT NULL,
  plan_ref JSONB NULL,

  artifact_refs JSONB NULL,
  body JSONB NOT NULL,

  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_receipts_caused_by
  ON receipts (caused_by_receipt_id);

CREATE INDEX IF NOT EXISTS idx_receipts_inbox_open
  ON receipts (recipient, phase, created_at);

CREATE INDEX IF NOT EXISTS idx_receipts_obligation
  ON receipts (obligation_id, created_at);

COMMIT;
