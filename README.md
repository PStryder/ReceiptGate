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

## Configuration

Environment variables (prefix `RECEIPTGATE_`). Generated from the `Settings`
class; MetaGate bootstrap variables are documented in their own section below.

`RECEIPTGATE_API_KEY` is **required** unless `RECEIPTGATE_ALLOW_INSECURE_DEV=true`; startup fails without it.

See `.env.example` for a working starting point.

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEIPTGATE_DEBUG` | `false` | Enable debug mode |
| `RECEIPTGATE_HOST` | `0.0.0.0` | Server bind address |
| `RECEIPTGATE_PORT` | `8000` | Server port |
| `RECEIPTGATE_SERVICE_NAME` | `receiptgate` | Service name |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEIPTGATE_AUTO_MIGRATE_ON_STARTUP` | `true` | Apply schema files on startup (dev friendly) |
| `RECEIPTGATE_DATABASE_URL` | `sqlite:///./receiptgate.db` | SQLAlchemy database URL |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEIPTGATE_ALLOW_INSECURE_DEV` | `false` | Allow unauthenticated access (dev only) |
| `RECEIPTGATE_API_KEY` | *(empty)* | API key for authentication |
| `RECEIPTGATE_DEFAULT_TENANT_ID` | `default` | Default tenant identifier for single-tenant deployments |
| `RECEIPTGATE_TRUSTED_HOSTS` | *(empty)* | Trusted hostnames |

### CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEIPTGATE_CORS_ALLOW_CREDENTIALS` | `true` | Allow credentials in CORS requests |
| `RECEIPTGATE_CORS_ALLOWED_HEADERS` | `['Authorization', 'Content-Type', 'X-API-Key']` | Allowed request headers |
| `RECEIPTGATE_CORS_ALLOWED_METHODS` | `['GET', 'POST', 'OPTIONS']` | Allowed HTTP methods |
| `RECEIPTGATE_CORS_ALLOWED_ORIGINS` | `['http://localhost:3000', 'http://localhost:8080']` | Allowed CORS origins |

### Behaviour and limits

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEIPTGATE_ENABLE_GRAPH_LAYER` | `true` | Apply graph schema (003) on startup |
| `RECEIPTGATE_ENABLE_SEMANTIC_LAYER` | `false` | Apply embeddings schema (004) on startup |
| `RECEIPTGATE_ENFORCE_CAUSE_EXISTS` | `false` | Require caused_by_receipt_id to exist |
| `RECEIPTGATE_LOG_RECEIPT_BODIES` | `false` | Log receipt bodies (discouraged for sensitive payloads) |
| `RECEIPTGATE_PUBLIC_URL` | `http://localhost:8000` | Public base URL for MCP clients |
| `RECEIPTGATE_RECEIPT_BODY_MAX_BYTES` | `262144` | Max body size in bytes |
| `RECEIPTGATE_RECEIPT_CHAIN_MAX_DEPTH` | `2048` | Max chain traversal depth |
| `RECEIPTGATE_SEARCH_DEFAULT_LIMIT` | `50` | Default search limit |
| `RECEIPTGATE_SEARCH_MAX_LIMIT` | `500` | Max search limit |

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
