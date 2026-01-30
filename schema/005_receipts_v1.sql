BEGIN;

CREATE TABLE IF NOT EXISTS receipts_v1 (
  uuid UUID PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  receipt_id TEXT NOT NULL,
  stored_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  recipient_ai TEXT NOT NULL,
  task_id TEXT NOT NULL,
  phase TEXT NOT NULL CHECK (phase IN ('accepted', 'complete', 'escalate')),
  caused_by_receipt_id TEXT NOT NULL,
  archived_at TIMESTAMPTZ NULL,
  payload JSONB NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_v1_tenant_receipt
  ON receipts_v1 (tenant_id, receipt_id);

CREATE INDEX IF NOT EXISTS idx_receipts_v1_inbox
  ON receipts_v1 (tenant_id, recipient_ai, phase, stored_at);

CREATE INDEX IF NOT EXISTS idx_receipts_v1_task
  ON receipts_v1 (tenant_id, task_id, stored_at);

CREATE INDEX IF NOT EXISTS idx_receipts_v1_caused_by
  ON receipts_v1 (tenant_id, caused_by_receipt_id);

COMMIT;
