# ReceiptGate Profile

ReceiptGate is a MemoryGate profile configured to store receipts as the canonical
obligation ledger.

## What it stores
- Receipts (immutable, append-only)

## What it does NOT store
- Durable task state (tasks remain ephemeral and are owned by AsyncGate)
- Artifacts (owned by DepotGate; only references are stored here)
- Execution runtime state

## Setup
1. Apply schema migrations in `schema/` (mirrors `../../schema/`)
2. Optionally run `jobs/build_receipt_graph.py`
3. Optionally run `jobs/build_receipt_embeddings.py` (stubbed)

## Env
- DATABASE_URL
- RECEIPTGATE_API_KEY (unless RECEIPTGATE_ALLOW_INSECURE_DEV=true)
- (optional) OPENAI_API_KEY for embeddings
