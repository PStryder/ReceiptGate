Gate v1 Exit Criteria

Component: ReceiptGate
Repo: https://github.com/PStryder/ReceiptGate
Owner: Technomancy Labs
Target tag: receiptgate-v1.0.0
Date locked: 2026-02-03

Definition of Done

1) Build & Run

- [x] One-command local run exists (`run_local.sh`, `run_local.ps1`).
- [x] Cold start succeeds (import + startup path).
- [x] Health endpoint returns OK (`receiptgate.health` MCP tool).
- [x] Config documented (README + `.env.example`).
- [ ] Container build verified (no Dockerfile in repo).

Artifacts:
- Run instructions: `ReceiptGate/README.md`
- Example env: `ReceiptGate/.env.example`

2) API & Contract Stability

- [x] MCP tool surface is the v1 contract (`/mcp`, tools/list + tools/call).
- [x] Request/response schemas are stable and in code (`src/receiptgate/mcp/routes.py`).
- [x] Error model is JSON-RPC error envelope.
- [x] REST endpoints removed; MCP-only.

Notes on v1 contract limitations:
- v1 is single-tenant (tenant_id assigned server-side).
- Graph + semantic layers are optional and disabled by default.

3) Canonical Principals (String IDs)

- [x] `SYSTEM_PRINCIPAL_ID = "sys:legivellum"`
- [x] `SERVICE_PRINCIPAL_ID = "svc:receiptgate"`

4) Receipt Model Invariants

- [x] Schema enforcement via JSON Schema (`schema/receipt.schema.v1.json`).
- [x] Terminal phases explicitly defined (`TERMINAL_PHASES = {"complete","escalate"}`).
- [x] Routing invariant enforced for escalation (`recipient_ai == escalation_to`).
- [x] Inbox derivation excludes terminal phases.

5) Persistence & Migration

- [x] Schema files `schema/001-005` apply cleanly (tested in `tests/test_migrations.py`).
- [x] SQLite default for dev; PostgreSQL supported.

DB notes:
- Storage engine: SQLite (dev), PostgreSQL (prod)
- Migration tool: SQL files in `schema/`

6) Core Behavioral Guarantees (Standalone)

Golden path:
submit receipt → inbox derivation → chain traversal → search.

- [x] Golden path demo script exists (`scripts/golden_path.py`).
- [x] Idempotency enforced by canonical hash (same receipt_id + hash → 200; mismatch → 409).

7) Test Requirements

- [x] Unit tests cover idempotency, validation, inbox derivation, chain traversal.
- [x] Regression tests exist for scary bits:
  - idempotency replay/conflict
  - phase transition validation
  - escalation routing invariant
  - terminal receipt detection

Test command:
`pytest tests/ -v`

8) Observability & Debuggability

- [x] Logs include correlation keys (receipt_id, task_id, recipient_ai).
- [x] Query path exists: list_inbox, search, list_task_receipts, get_receipt_chain.
- [x] Failure modes surfaced via JSON-RPC error envelopes.

9) v1 Lock Rules

Frozen at tag:
- Receipt schema + terminal phase semantics
- MCP tool surface + error envelope
- DB schema (unless migration plan)

10) Open Issues / Deferred Work

- [ ] Container build verification (if/when Dockerfile is added).
- [ ] Tag receiptgate-v1.0.0 after final sign-off.

Sign-off

- Owner sign-off: pending
- Integration readiness confirmed: pending
- Tag created: pending
