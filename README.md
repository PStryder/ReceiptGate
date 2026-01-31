# ReceiptGate

ReceiptGate is the canonical receipt ledger for the LegiVellum stack. It is a
MemoryGate profile that stores immutable, append-only receipts and derives
obligation truth (inbox, chain, history) from those receipts.

## What it is
- Immutable receipt ledger
- Idempotent append-only API
- Derived inbox/chain endpoints

## What it is not
- Durable task store (AsyncGate owns task lifecycle)
- Artifact store (DepotGate owns artifact storage)
- Workflow runtime

## Quick Start

```bash
# Install dependencies
pip install -e .

# One-command local run
./run_local.sh
# Windows PowerShell: .\run_local.ps1
```

Health check:

```bash
curl http://localhost:8000/health
```

Schema files live in `schema/` and can be auto-applied on startup when
`RECEIPTGATE_AUTO_MIGRATE_ON_STARTUP=true` (default).

## Golden Path Demo

```bash
python scripts/golden_path.py
```

## API Endpoints

- `POST /receipts` - Append a receipt (idempotent)
- `GET /receipts/{receipt_id}` - Fetch receipt
- `GET /receipts/{receipt_id}/chain` - Causality chain
- `POST /receipts/search` - Search receipts
- `GET /inbox/{recipient}` - Open obligations for recipient
- `GET /receipts/stats` - Summary stats
- `GET /health` - Health check

## Receipt Phases & Termination

Receipt phases (REST API): `accepted`, `complete`, `escalate`, `cancel`.

Terminal phases for obligation closure:
- `complete`
- `escalate`
- `cancel`

LegiVellum v1 receipts (MCP) use terminal phases `complete` and `escalate`.

## Canonical Principals

Defined in `src/receiptgate/principals.py`:
- `SYSTEM_PRINCIPAL_ID = "sys:legivellum"`
- `SERVICE_PRINCIPAL_ID = "svc:receiptgate"`

## Environment

See `.env.example` for the full list. Key variables:

- `RECEIPTGATE_DATABASE_URL` (default: `sqlite:///./receiptgate.db`)
- `RECEIPTGATE_API_KEY` (unless `RECEIPTGATE_ALLOW_INSECURE_DEV=true`)
- `RECEIPTGATE_ALLOW_INSECURE_DEV` (dev only)
- `RECEIPTGATE_RECEIPT_BODY_MAX_BYTES` (default 262144)
- `RECEIPTGATE_ENABLE_GRAPH_LAYER` / `RECEIPTGATE_ENABLE_SEMANTIC_LAYER`

## Tests

```bash
pytest tests/ -v
```
