BEGIN;

CREATE TABLE IF NOT EXISTS receipt_edges (
  from_receipt_id TEXT NOT NULL,
  to_receipt_id   TEXT NOT NULL,
  edge_type TEXT NOT NULL CHECK (edge_type IN ('caused_by')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (from_receipt_id, to_receipt_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_receipt_edges_to
  ON receipt_edges (to_receipt_id);

COMMIT;
