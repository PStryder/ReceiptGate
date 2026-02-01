# ReceiptGate Policy

ReceiptGate is a MemoryGate profile acting as the canonical receipt ledger.

## Canonical Truth
- Receipts are append-only and immutable.
- Obligation truth is derived from receipts alone.
- Derived layers (graph/embeddings) must be rebuildable from canonical receipts.

## Explicit Non-Responsibilities
- ReceiptGate does not execute tasks.
- ReceiptGate does not route work.
- ReceiptGate does not push notifications.
- ReceiptGate does not store durable task state.
- ReceiptGate does not store artifacts (only references).

## Allowed References
- task_ref.task_id may be present as a reference to AsyncGate execution context.
- artifact_refs may be present as references to DepotGate outputs.
- plan_ref may be referenced, but storing plans is profile-configurable.
