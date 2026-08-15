# ReceiptGate

ReceiptGate is the canonical receipt ledger for the LegiVellum stack. It is a
MemoryGate profile that stores immutable, append-only receipts and derives
obligation truth (inbox, chain, history) from those receipts.

## What it is
- Immutable receipt ledger
- Idempotent append-only MCP interface
- Derived inbox/chain tools

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
curl -s http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"receiptgate.health","arguments":{}}}'
```

Schema files live in `schema/` and can be auto-applied on startup when
`RECEIPTGATE_AUTO_MIGRATE_ON_STARTUP=true` (default).

## Golden Path Demo

```bash
python scripts/golden_path.py
```

## MCP Interface

ReceiptGate is MCP-only (JSON-RPC over HTTP). The MCP endpoint is:

```
POST /mcp
```

Tool names:
- `receiptgate.submit_receipt` - Append a receipt (idempotent)
- `receiptgate.list_inbox` - Open obligations for recipient
- `receiptgate.get_receipt_chain` - Causality chain
- `receiptgate.search_receipts` - Search receipt headers
- `receiptgate.list_task_receipts` - All receipts for a task
- `receiptgate.get_receipt` - Fetch full receipt payload
- `receiptgate.bootstrap` - Open a session for an agent: returns its inbox plus ledger config (schema version, endpoint, limits). Requires `agent_name` and `session_id`. Distinct from `metagate.bootstrap`, which resolves topology for a *service*; this one hands an *agent* its open obligations.
- `receiptgate.health` - MCP health check


## Receipt Phases & Termination

Terminal phases for obligation closure:
- `complete`
- `escalate`

LegiVellum v1 receipts use terminal phases `complete` and `escalate`.

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

## MetaGate Bootstrap

On startup this gate asks MetaGate for the topology it belongs to and fills in
endpoints the operator did not configure. It declares no endpoint bindings: ReceiptGate is a leaf, so everything calls it and it calls no other primitive.

| Variable | Default | Meaning |
|----------|---------|---------|
| `RECEIPTGATE_METAGATE_ENDPOINT` | *(unset)* | MetaGate MCP endpoint. Unset disables bootstrap; the gate starts on configured values alone. |
| `RECEIPTGATE_METAGATE_API_KEY` | *(unset)* | Credential presented to MetaGate |
| `RECEIPTGATE_METAGATE_COMPONENT_KEY` | `receiptgate` | Which component in the manifest this process is |
| `RECEIPTGATE_METAGATE_BOOTSTRAP_TIMEOUT_SECONDS` | `5.0` | Per-call timeout |

Bootstrap never prevents startup. Every failure — unreachable, timeout, auth
rejected, no binding, malformed packet — degrades to a logged warning and
"carry on with configured values", because a bootstrap authority that can take
the mesh down would be a hidden master. Explicit configuration always wins;
bootstrap fills gaps and logs when the mesh disagrees rather than overriding.

See `LegiVellum/docs/canonical/metagate.bootstrap.md` for the full contract.
