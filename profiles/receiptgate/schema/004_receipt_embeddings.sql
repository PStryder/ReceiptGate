BEGIN;

CREATE TABLE IF NOT EXISTS receipt_embeddings (
  receipt_id TEXT PRIMARY KEY REFERENCES receipts(receipt_id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dims INT NOT NULL,
  embedding VECTOR(1536) NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Optional vector index (pgvector)
-- CREATE INDEX IF NOT EXISTS idx_receipt_embeddings_vec
--   ON receipt_embeddings USING ivfflat (embedding vector_l2_ops);

COMMIT;
