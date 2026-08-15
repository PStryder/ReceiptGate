<!-- Generated 2026-08-15. Stack-level context: ../LV_STACK_REVIEW.md -->

> **Review 2 — ReceiptGate**
> Part of a full-stack review of LV_Stack (11 repos, ~97k LOC) conducted 2026-08-15.
> Stack-wide findings that affect this repo but are not fixable inside it are in
> `../LV_STACK_REVIEW.md` and `../_CROSS_REPO_ANALYSIS.md`. Read the stack report first —
> several findings below have a shared root cause.

---

# ReceiptGate — Code Review

Reviewed at: `/home/claude/lv/ReceiptGate/` (HEAD as extracted; repo listed CLEAN in `BASELINE_FREEZE_2026-02-23.md`).
No prior `CODE_REVIEW*.md` exists in this repo, so there is no fix-regression history to score against.

## Verdict

The JSON Schema file is byte-identical to canonical and the validation wiring around it is genuinely good — that part is done. Everything *around* the schema is not: ReceiptGate enforces **zero** obligation-lifecycle invariants (no accept-before-complete, no already-terminated check, no authority binding), and its terminator detection closes obligations by bare `task_id` match, which is precisely the "any matching parent closes" antipattern §4 of the Exit Criteria Template forbids. Any holder of the single shared API key can mint a `complete` receipt for any `task_id` and silently close another principal's obligation; an `accepted` receipt minted after a terminal receipt on the same `task_id` is invisible from birth and no error is returned. For the repo whose entire job is being right about obligations, this is not v1-taggable.

Secondary but disqualifying: the write path raises `TypeError` on every successful store the moment INFO logging is enabled (`ledger_v1.py:86`), two of the three storage layers are dead (the graph job reads an empty legacy table; the embeddings job raises `NotImplementedError`), and the repo ships three mutually contradictory "authoritative" protocol specs.

## Exit Criteria Scorecard

Scored against `/home/claude/lv/Gate v1 Exit Criteria Template.txt`.

| § | Section | Score | Justification |
|---|---|---|---|
| 1 | Build & Run | **PARTIAL** | `run_local.sh`/`.ps1`, health tool, README + `.env.example` all present; no Dockerfile, and the repo's own criteria file already concedes it. |
| 2 | API & Contract Stability | **PARTIAL** | MCP-only surface with a JSON-RPC error envelope is stable, but errors mix numeric JSON-RPC codes (`-32601`) with string codes (`"validation_failed"`, `"RECEIPT_ID_COLLISION"`) in the same field, and unvalidated args escape as unhandled 500s (F-14). |
| 3 | Canonical Principals | **PARTIAL** | Constants are correct (`principals.py:3-4`), but **no ownership rule is enforced anywhere** — `from_principal`, `for_principal`, `source_system`, `recipient_ai` are 100% client-controlled and never checked against the authenticated caller (F-1). |
| 4 | Receipt Model Invariants | **FAIL** | `TERMINAL_PHASES` is an explicit set (`validation_v1.py:24`) ✓, but terminator detection is `task_id`-scoped, not lineage- or recipient-gated (F-3); non-terminal receipts cannot close only because the phase enum has 3 values, not because anything checks; `canceled` is a `status` that is never stored as a column and never tested; no retryable-vs-terminal distinction exists. |
| 5 | Persistence & Migration | **PARTIAL** | `schema/001-005` apply cleanly from empty and are tested (`test_migrations.py:14`), but 001/002/004 are dead legacy tables with a *conflicting* phase enum incl. `'cancel'` and an `ON DELETE CASCADE` FK (F-17), and no upgrade path is documented for the 001→005 split. |
| 6 | Core Behavioral Guarantees | **PARTIAL** | `scripts/golden_path.py` covers accept → inbox → complete → chain → inbox-closed. But the "long-running / no infinite wait" clause fails: `get_receipt_chain` on a self-caused receipt issues 2048 serial queries and returns 2048 duplicate rows (F-6). |
| 7 | Test Requirements | **FAIL** | Of the five required regressions, one is covered (dedupe/hash), one is half-covered (terminal detection — unit-level only), and three are absent: cancel-closes, ack/progress/anomaly-does-not-close, lease-invariants (N/A). See Test Coverage Gaps. |
| 8 | Observability & Debuggability | **FAIL** | The single correlation log line is a `TypeError` waiting to fire (F-5); at default log level nothing is logged at all. Query paths exist ✓. Failure modes are *not* all visible: silently-invisible obligations (F-2, F-7) surface as success responses. |
| 9 | v1 Lock Rules | **FAIL** | Cannot freeze semantics that three in-repo specs disagree about (F-20), and the DB schema would need a breaking change to fix F-3/F-11. |
| 10 | Open Issues / Deferred | **PARTIAL** | `RECEIPTGATE_V1_EXIT_CRITERIA.md:88-91` lists only Dockerfile + tagging. It does not disclose the unimplemented lifecycle invariants, the dead graph/semantic layers, or `RECEIPTGATE_ENFORCE_CAUSE_EXISTS` being a no-op — all of which are advertised as working. |

**Blunt verdict on v1-taggability: NO.** §4, §7, §8, §9 fail. §4 and §7 are the two sections that exist specifically to prevent an obligation ledger from being wrong, and both fail on the same root cause.

## Canonical Schema Conformance

**JSON Schema: no drift.** `ReceiptGate/schema/receipt.schema.v1.json` is byte-identical to `LegiVellum/docs/canonical/receipt.schema.v1.json` (`diff` returns empty). Verified programmatically: 42 properties, 41 required, `artifact_refs` the sole optional, `additionalProperties: false`. `additionalProperties: false` **is** enforced at the API boundary — `routes.py:178` calls `validate_receipt_payload` → `validation_v1.py:102 jsonschema.validate(payload, schema)` before `put_receipt`, on the write path, not advisory. Server-assigned fields are applied *before* validation (`routes.py:177`) so client-omitted `tenant_id`/`stored_at` still validate. This is the strongest part of the repo.

**Drift is at the storage and query layer, not the schema layer.** The 42-field receipt is stored as an opaque JSON blob with only 8 promoted columns:

| Canonical requirement | `receipts_v1` (`schema/005_receipts_v1.sql`) | Impact |
|---|---|---|
| `parent_task_id` (required field; `receipt.indexes.sql:18` mandates `idx_receipts_parent_task_id`; `receipt.rules.md:198-204` defines the Delegation Tree query) | **not a column** — JSON only, no index, no tool exposes it | The canonical "Delegation Tree" query is **unimplementable** through the MCP surface. Delegation lineage is write-only. |
| `status` (`success`/`failure`/`canceled`; the only way `canceled` is expressed in v1) | **not a column**, no search filter | Cannot ask "which obligations were canceled vs failed" without a full-table JSON scan. Exit Criteria §4's mandatory terminal outcomes are unqueryable. |
| `dedupe_key` (`receipt.rules.md:170-172`) | stored in JSON, **never read by any code path** | Advertised idempotency key is inert. |
| `read_at` (inbox read time) | **not a column**, no write path | Never settable; permanently `null`. |
| `receipt.store.md:305-316` chain = recursive CTE over `r.caused_by_receipt_id = c.receipt_id` (**descendants**) | `ledger_v1.py:350-360` walks `current_id = row.caused_by_receipt_id` (**ancestors**) | Opposite direction. See F-8. |
| `receipt.rules.md:157-159` — order by `stored_at`, then `created_at` | `ORDER BY stored_at` only (`ledger_v1.py:205`, `:295`) | Non-deterministic ordering for same-`stored_at` receipts. |
| `receipt.schema.v1.json` phase enum = `{accepted, complete, escalate}` | `schema/001_receipts.sql:8` CHECK allows `'cancel'`; `002_receipt_views.sql:11` treats `'cancel'` as terminal | Dead legacy table encodes a phase the canonical model deleted. See F-17. |
| `receipt.schema.v1.json` — `receipt_id`/`from_principal`/`for_principal`/`source_system`/`recipient_ai` "Must not be `NA` or `TBD` by policy" | no code enforces this (`grep '"NA"' src/` → only defaulting and chain-sentinel usage) | See F-10. |

## Critical & High Findings

### F-1 — CRITICAL — No authority binding: any caller can mint a receipt as any principal, for any obligation

`src/receiptgate/mcp/routes.py:174-183`
```python
if tool_name == "receiptgate.submit_receipt":
    receipt = arguments.get("receipt") or {}
    stored_at = receiptgate_clock()
    payload = apply_server_fields(receipt, tenant_id=tenant_id, stored_at=stored_at)
    errors = validate_receipt_payload(payload)
    ...
    result = put_receipt(db, payload, tenant_id)
```
`src/receiptgate/validation_v1.py:126-131` — `apply_server_fields` sets **only** `tenant_id` and `stored_at`. Every identity field (`from_principal`, `for_principal`, `source_system`, `recipient_ai`, `task_id`) is taken verbatim from the request body. `auth.py:22-61` verifies one shared global API key and returns `True` — it carries no principal, so there is nothing to bind to.

LegiVellum invariant #1 is "only Principals and DeleGates may mint obligations". ReceiptGate performs no check of any kind.

**Failure scenario.** CogniGate holds the shared `RECEIPTGATE_API_KEY` (every component must, to write receipts). It submits `{phase: "complete", task_id: "T-payroll-run", status: "success", outcome_kind: "none", recipient_ai: "agent:finance", from_principal: "sys:legivellum", source_system: "delegate", completed_at: ...}`. Schema validation passes (all 41 fields present and phase-consistent). The receipt is stored. `list_inbox(recipient_ai="agent:finance")` now excludes `T-payroll-run` forever (`ledger_v1.py:157-162`). A component with no authority over that obligation has forged a discharge attributed to DeleGate, and the ledger records it as truth. The audit trail is now actively wrong, and there is no path to correct it because receipts are append-only.

**Fix.** Derive a caller principal from the credential (per-component API keys or JWT `sub`) and reject on write when `source_system` does not match the authenticated caller. At minimum, store the authenticated caller in a server-assigned `submitted_by` column so forgery is *detectable* even if not prevented.

---

### F-2 — CRITICAL — Obligation lifecycle invariants are entirely unimplemented; `accepted` after a terminal receipt is silently swallowed

`src/receiptgate/ledger_v1.py:99-144` — `put_receipt` performs exactly two checks: `receipt_id` present, and canonical-hash idempotency. There is no query for prior receipts on the `task_id`.

The repo's own `receipts.put Contract.txt:266-278` enumerates the error codes that are required and absent:
```
OBLIGATION_ALREADY_TERMINATED (409)
COMPLETE_WITHOUT_ACCEPT (409)
ESCALATE_WITHOUT_ACCEPT (409)
CANCEL_WITHOUT_ACCEPT (409)
```
`Receipt Protocol Golden.txt:167-186` restates them normatively ("Obligation must not already be terminated", "A prior `accepted` receipt must exist"). `grep -rn "ALREADY_TERMINATED\|WITHOUT_ACCEPT" src/` returns nothing.

**Failure scenario (the dangerous one — it returns success).** Task `T-9` fails: agent emits `complete`/`status=failure`. A supervisor retries by minting a fresh `accepted` receipt for `T-9` (same `task_id`, `attempt=1`, `parent_task_id=NA`). `put_receipt` stores it and returns `{"idempotent_replay": false}` — success. But `list_inbox` (`ledger_v1.py:157-162`) sees the pre-existing `complete` on `T-9` and suppresses the new `accepted` row. The obligation exists in the ledger, the supervisor believes it was assigned, the agent never sees it, and no error was raised at any point. Work is lost with a green receipt as evidence it was assigned.

Symmetrically: a second `complete` on an already-completed `task_id` is accepted, so the ledger can contain two contradictory terminal dispositions (`success` and `failure`) for one obligation with nothing indicating which is authoritative.

**Fix.** Inside the same transaction as the INSERT, `SELECT ... FROM receipts_v1 WHERE tenant_id=? AND task_id=? AND phase IN (:terminal) FOR UPDATE` (or rely on a partial unique index `UNIQUE(tenant_id, task_id) WHERE phase IN ('complete','escalate')` to make double-termination structurally impossible), and reject with the documented 409 codes.

---

### F-3 — CRITICAL — Terminator detection is `task_id`-scoped, not lineage- or recipient-gated ("any matching parent closes")

`src/receiptgate/ledger_v1.py:149-166`
```python
WHERE tenant_id = :tenant_id
  AND recipient_ai = :recipient_ai
  AND phase = 'accepted'
  AND archived_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM receipts_v1 t
    WHERE t.tenant_id = r.tenant_id
      AND t.task_id = r.task_id
      AND t.phase IN :terminal_phases
  )
```
The `NOT EXISTS` correlates on `task_id` alone. It does not correlate on `recipient_ai`, does not follow `caused_by_receipt_id`, and does not require the terminal receipt to descend from the `accepted` receipt it closes. Exit Criteria Template line 73 requires "Terminator detection is type-gated (not 'any matching parent closes')" — the type gate is present (`phase IN :terminal_phases`), but the *scoping* gate is exactly the forbidden pattern with `task_id` substituted for "parent".

**Failure scenario.** Fan-out: DeleGate assigns review of `task_id = "T-contract-42"` to two reviewers, minting `accepted` receipts `r-a` (`recipient_ai: agent:alice`) and `r-b` (`recipient_ai: agent:bob`) — same `task_id`, per the canonical model where `task_id` is "stable correlation key for the lifecycle of a task instance". Alice completes: `r-a-c`, `phase=complete`, `task_id=T-contract-42`. The `NOT EXISTS` now matches for **both** rows. Bob's obligation vanishes from his inbox although Bob emitted nothing. Bob has an outstanding, unreleased obligation that no query can surface, and `list_inbox` reports zero.

The same mechanism means a `complete` from an unrelated lineage (F-1) closes an obligation it never touched.

**Fix.** Correlate the terminator on the obligation instance, not the task: either add an `obligation_id` column (which the repo's own `001_receipts.sql:11` and Golden spec already use) and scope `NOT EXISTS` to it, or require `t.caused_by_receipt_id = r.receipt_id` so only a receipt descended from the accept can close it.

---

### F-4 — CRITICAL — Escalation delivers nothing: the "soft push" target never sees the obligation

`src/receiptgate/ledger_v1.py:154` — `AND phase = 'accepted'`. Only `accepted` receipts are inbox-visible. `validation_v1.py:24` — `TERMINAL_PHASES = {"complete", "escalate"}`, so an `escalate` receipt is terminal for its `task_id` (F-3 scoping).

`receipt.schema.v1.json:7` describes escalate as "transfers/transforms responsibility (**soft push to a target inbox**)" and `receipt.rules.md:57` as "LegiVellum's **only soft push mechanism**: the receipt is routed to `recipient_ai = escalation_to`". `validate_routing_invariant` (`validation_v1.py:69-78`) correctly enforces `recipient_ai == escalation_to` — and then the receipt is routed into an inbox query that filters it out.

**Failure scenario.** Agent A cannot complete `T-7` and escalates: `{phase: "escalate", task_id: "T-7", recipient_ai: "agent:b", escalation_to: "agent:b", escalation_class: "capability"}`. Validation passes, the receipt stores. Then:
1. `list_inbox("agent:a")` → `T-7` gone (escalate is terminal). Correct.
2. `list_inbox("agent:b")` → **empty**. The escalate receipt is not `phase='accepted'`, so B is never told anything was pushed to it.
3. B (if told out-of-band) mints `accepted` for `task_id="T-7"` to take ownership → the existing terminal `escalate` on `T-7` suppresses it (F-3). B's new obligation is dead on arrival, silently.

The obligation is now closed for A, invisible to B, and unre-openable under the same `task_id`. `receipt.rules.md:64-67` says the new owner continues "by issuing new `accepted` task(s)" — implying a *new* `task_id` — but nothing in ReceiptGate enforces, documents, or tests that, and the failure mode when the rule is violated is silent loss rather than an error. `Escalation Semantics.txt:148-198` specifies an explicit `v_obligation_open_events` view precisely to fix this; it was never built.

**Fix.** Either (a) surface `escalate` receipts in the target's inbox as open events, or (b) reject an `accepted` receipt whose `task_id` already carries a terminal receipt (F-2) so the dead-on-arrival case becomes a loud 409, and document that escalation requires a fresh `task_id` with `parent_task_id` set.

---

### F-5 — HIGH — The only write-path log line raises `TypeError`, failing every successful store once INFO logging is on

`src/receiptgate/ledger_v1.py:5-17, 81-96`
```python
import logging
logger = logging.getLogger(__name__)
...
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "receiptgate_v1_receipt_stored",
        receipt_id=receipt_id,
        tenant_id=tenant_id,
        task_id=record.get("task_id"),
        ...
    )
```
This is structlog-style kwargs against a **stdlib** logger. `grep -rn "structlog" .` returns nothing; structlog is not in `pyproject.toml` dependencies. Verified: `logging.Logger.info` accepts only `exc_info`/`stack_info`/`stacklevel`/`extra`; anything else raises `TypeError: Logger._log() got an unexpected keyword argument 'receipt_id'`. It is latent today only because the root logger defaults to WARNING and `isEnabledFor(INFO)` short-circuits before kwargs are unpacked.

**Failure scenario.** Operator runs `uvicorn --log-level info` (or any deployment that calls `logging.basicConfig(level=INFO)` — the normal production posture). Client calls `receiptgate.submit_receipt`. The INSERT commits at line 81. Line 86 raises `TypeError`. It is raised *outside* the `try/except` at 65-84, so it is not the `IntegrityError` `put_receipt:124` expects; it propagates to `routes.py:195-201` and returns `{"code": "receiptgate_error", "message": "Failed to store receipt"}`. **The receipt is durably committed but the client is told the write failed.** The client retries; the retry hits the idempotent-replay path (`put_receipt:106-115`), which returns *before* reaching the log line, so the retry succeeds. Net effect: every first-write returns a spurious error, retry-less clients treat committed receipts as lost, and — combined with F-2 — a client that responds to the "failure" by minting a different receipt for the same obligation corrupts the ledger.

Note `.mypy-ci.ini` disables `call-arg`, the exact error code that would have caught this in CI.

**Fix.** `logger.info("receipt_stored", extra={...})` or an f-string. Remove `call-arg` from the mypy disable list.

---

### F-6 — HIGH — No cycle detection in lineage; `ENFORCE_CAUSE_EXISTS` is documented but is a no-op

`src/receiptgate/ledger_v1.py:340-362`
```python
    while current_id and current_id != "NA" and depth < max_depth:
        row = _get_receipt_row(db, tenant_id, current_id)
        if not row:
            break
        chain.append({...})
        current_id = row.get("caused_by_receipt_id")
        depth += 1
```
No visited-set. The only bound is `max_depth`, defaulting to **2048** (`config.py:65`), and each hop is a separate round-trip (N+1).

`src/receiptgate/config.py:68-71` declares `enforce_cause_exists` and README line 127 documents `RECEIPTGATE_ENFORCE_CAUSE_EXISTS` as "Require caused_by_receipt_id to exist". `grep -rn "enforce_cause_exists" src/` matches **only** the config declaration. It is never read. Neither is the self-causation guard `receipts.put Contract.txt:231` requires ("Prevent self-causation: `receipt_id != caused_by_receipt_id`").

**Failure scenario A (cycle).** A buggy or hostile client submits `{receipt_id: "r-x", caused_by_receipt_id: "r-x"}` — schema-valid (both `minLength: 1` strings). Any later `receiptgate.get_receipt_chain({receipt_id: "r-x"})` performs 2048 serial DB round-trips and returns a 2048-element chain of the same receipt. Two clients doing this saturate the connection pool. A two-node cycle (`r-a → r-b → r-a`, each individually valid) does the same and is not detectable at write time without the cause-exists check.

**Failure scenario B (dangling parent).** A client submits `caused_by_receipt_id: "r-never-existed"`. Stored without complaint. `get_receipt_chain` breaks at line 353 and returns a truncated chain **indistinguishable from a complete one** — no marker says the chain was cut. Invariant #4 ("receipts form complete causality chains") is unverifiable, and the operator who set `RECEIPTGATE_ENFORCE_CAUSE_EXISTS=true` believes it is being verified.

**Fix.** Add a `visited: set[str]` to the traversal and break with an explicit `"truncated": "cycle"` marker; return `"truncated": "missing_parent"` when the parent lookup fails. Implement `enforce_cause_exists` in `put_receipt` (existence check in the write transaction) plus an unconditional `receipt_id != caused_by_receipt_id` rejection, or delete the setting and its README row.

---

### F-7 — HIGH — Client-supplied `archived_at` makes an obligation invisible from birth

`src/receiptgate/ledger_v1.py:61` — `"archived_at": payload.get("archived_at"),` — taken directly from the client payload.
`src/receiptgate/ledger_v1.py:155` — `AND archived_at IS NULL`.

`receipt.schema.v1.json:334-388` — the `phase: accepted` conditional constrains `status`, `completed_at`, `task_summary`, all `outcome_*`, all `artifact_*`, `escalation_*`, and `retry_requested`. It does **not** constrain `archived_at`. `receipt.store.md:81` calls `archived_at` "the only mutable field (soft delete)" — implying a server-controlled archive operation, of which none exists in the codebase.

**Failure scenario.** A client submits an otherwise perfectly valid `accepted` receipt with `archived_at: "2020-01-01T00:00:00Z"`. Validation passes. `store_receipt` writes it. `list_inbox` filters it out at line 155. The obligation exists in the ledger and in `list_task_receipts` output, so an audit says it was created — but it never appeared in any inbox and no error was raised. This is a one-field mechanism for minting an obligation that is provably assigned and provably never deliverable.

**Fix.** Reject non-null `archived_at` on `phase: accepted` at submit (application-level, as with the routing invariant), or make `archived_at` server-assigned-only and ignore the client value.

---

### F-8 — HIGH — `get_receipt_chain` traverses the opposite direction from the canonical spec

`src/receiptgate/ledger_v1.py:359` — `current_id = row.get("caused_by_receipt_id")` — walks **upward** to ancestors.

`receipt.store.md:305-316` and `receipt.rules.md:206-217` both specify the chain as a recursive CTE joining `r.caused_by_receipt_id = c.receipt_id` — i.e. **downward**, collecting descendants of the seed receipt.

**Failure scenario.** InterView (or any auditor) calls `get_receipt_chain({receipt_id: "<the accepted receipt>"})` to answer "what did this obligation cause?" — the natural question, and the one the canonical CTE answers. Because the `accepted` receipt has `caused_by_receipt_id: "NA"`, the loop condition at line 350 fails on the first iteration after append and the response is `{"chain": [<just the accept>]}`. The caller reads this as "this obligation caused nothing" when in fact a full escalation tree hangs off it. The repo's own test bakes the wrong direction in: `tests/test_mcp.py:170` asserts `chain_ids == ["r-5c", "r-5"]`.

**Fix.** Either implement the canonical descendant CTE, or add a `direction` argument defaulting to the canonical one — and update `receipt.store.md` if the ancestor walk is the intended contract. Do not leave two canonical documents describing the opposite of the shipped behaviour.

---

### F-9 — HIGH — Append-only/immutability is convention only; nothing enforces it at the DB layer

`profiles/receiptgate/profile.yaml:28-30`
```yaml
  immutability:
    receipts_append_only: true
    forbid_update_delete: true
```
`receipts.put Contract.txt:209-211` — "No updates/deletes allowed **at DB level (policy)** and API level". `receipt.rules.md:249-254` — "Receipts MUST be immutable after insertion".

Actual state: `grep -rni "UPDATE |DELETE " src/ schema/` finds **no** UPDATE/DELETE against `receipts_v1` — the application genuinely has no mutation path, which is good. But there is no `REVOKE UPDATE, DELETE ON receipts_v1`, no `BEFORE UPDATE OR DELETE ... RAISE EXCEPTION` trigger, no append-only role, and no hash-chaining/sequence-number tamper evidence. `schema/004_receipt_embeddings.sql:4` even declares `REFERENCES receipts(receipt_id) ON DELETE CASCADE`, encoding an assumption that receipt deletion is a supported operation.

**Failure scenario.** ReceiptGate connects with a single DSN whose role owns the schema (required, since `auto_migrate_on_startup` defaults `true` and runs DDL). Any operator, any co-located service sharing that DSN, or any future code path can `UPDATE receipts_v1 SET payload = ... WHERE receipt_id = ...` and nothing detects it: `canonical_hash` is computed on write and **never stored** (`put_receipt:143` returns it to the client but the column does not exist in `005_receipts_v1.sql`; only the dead `001_receipts.sql:4` has a `canonical_hash` column). A silently edited receipt is unfalsifiable. For "the only global narrative", this is the difference between an audit ledger and a table.

**Fix.** Persist `canonical_hash` as a column on `receipts_v1` so tampering is detectable; add an append-only trigger on Postgres; run the app on a role with `INSERT, SELECT` only and do migrations under a separate role.

---

### F-10 — HIGH — `NA`/`TBD` sentinel policy is documented in the schema and enforced nowhere

`receipt.schema.v1.json` states "Must not be `'NA'` or `'TBD'` by policy" for `receipt_id` (:64), `from_principal` (:94), `for_principal` (:99), `source_system` (:104), and `recipient_ai` (:109). These are prose in `description`; JSON Schema only enforces `minLength: 1`. The `allOf` blocks cover `escalation_reason`/`task_summary` `TBD` for specific phases only. `grep '"NA"\|TBD' src/receiptgate/` finds only defaulting (`ledger_v1.py:57-60`) and the chain sentinel (`:350`) — no policy check anywhere.

**Failure scenario.** A misconfigured worker template submits `recipient_ai: "NA"` (its own inapplicable-field default). Validation passes. The receipt is stored with `recipient_ai = "NA"`. The obligation is now addressed to a literal inbox named `"NA"` that no agent polls; `list_inbox` for the intended agent returns nothing; `list_inbox("NA")` returns an accumulating pile of orphans nobody looks at. Same for `receipt_id: "NA"` — the receipt becomes unreachable by `get_receipt_chain`, which treats `"NA"` as the chain terminator (`:350`) and stops rather than fetching it.

Compounding: `ledger_v1.py:57-60` *defaults* missing `recipient_ai`/`task_id`/`caused_by_receipt_id` to `"NA"` and missing `phase` to `"accepted"` — a ledger that invents an obligation phase when the field is absent. That path is unreachable through the validated MCP route but is live for any direct `store_receipt` caller (which the tests are).

**Fix.** Add the five policy checks to `validate_receipt_payload` alongside `validate_routing_invariant`. Remove the `.get(..., "NA")` and `.get("phase", "accepted")` defaults in `store_receipt` — raise instead.

---

### F-11 — HIGH — Two of the three storage layers are dead; the graph job reads an empty table

`jobs/build_receipt_graph.py:13-19`
```python
SQL_INSERT = """
INSERT INTO receipt_edges (from_receipt_id, to_receipt_id, edge_type)
SELECT receipt_id, caused_by_receipt_id, %s
FROM receipts
WHERE caused_by_receipt_id IS NOT NULL
```
It reads `receipts` — the legacy `001` table. Every write goes to `receipts_v1` (`ledger_v1.py:69`). `grep -rn "INSERT INTO receipts\b" src/` → nothing. `receipts` is **never written**.

`jobs/build_receipt_embeddings.py:16-19` — `raise NotImplementedError("Embedding job not implemented.")`.

`schema/002_receipt_views.sql:5-16` — `v_open_obligations` / `v_inbox` also select `FROM receipts` and correlate on `obligation_id`, a column `receipts_v1` does not have. Both views are permanently empty and reference a phase (`'cancel'`) the canonical model deleted.

**Failure scenario.** An operator enables the graph layer (`RECEIPTGATE_ENABLE_GRAPH_LAYER=true`, the **default**), runs `python jobs/build_receipt_graph.py` nightly, and it exits 0 every night having inserted zero rows. Any consumer doing structural validation via `receipt_edges` — "receipt chain integrity = graph connectivity check" per `Three_Layer_Storage_Architecture.md:185-186` — reads an empty graph and concludes every chain is intact. A silent all-clear on an integrity check is worse than no check.

On archival/losslessness specifically: there is no hot/cold/archive tiering at all. `archived_at` is a column with no writer, and `retention.receipts.ttl_days: null` in `profile.yaml`. So "is archival lossless / can a cold-archived receipt still satisfy provenance lookups" is vacuously satisfied — nothing is ever archived. That is a defensible v1 stance, but it should be listed under §10 deferred work rather than implied to work.

**Fix.** Point the graph job at `receipts_v1` (and `tenant_id`-scope the edges), or delete `jobs/`, `002`, `003`, `004` and the `enable_graph_layer`/`enable_semantic_layer` settings from v1 and record them as deferred.

## Medium Findings

### F-12 — MEDIUM — `jsonschema` ImportError silently disables all validation

`src/receiptgate/validation_v1.py:10-14, 81-83`
```python
try:
    import jsonschema
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
...
def validate_json_schema(payload):
    if not JSONSCHEMA_AVAILABLE:
        return []
```
The comment at :87-92 explains at length why a *missing schema file* must fail closed ("A validator that cannot find its rules is misconfigured, not permissive") — and then the branch immediately above fails **open** for a missing library, which has identical consequences. `jsonschema>=4.21.1` is a hard dependency, so this requires a broken install to trigger; but a broken install is precisely when you want the loud failure. **Failure scenario:** a slim container image prunes `jsonschema`; ReceiptGate starts, health returns `healthy`, and accepts arbitrary JSON as receipts indefinitely.
**Fix:** drop the try/except and import at module scope, or raise the same `RuntimeError`.

### F-13 — MEDIUM — Unbounded queries: `search_max_limit` is never applied; `list_task_receipts` has no limit at all

`src/receiptgate/mcp/routes.py:255` — `limit = int(arguments.get("limit") or settings.search_default_limit)` — `settings.search_max_limit` (`config.py:67`, default 500, mandated by `profile.yaml:43`) is **never referenced outside its own validator**. `routes.py:242` — `limit = arguments.get("limit")` for `list_task_receipts`, passed as `None` → `ledger_v1.py:194` sets `limit_clause = ""`, i.e. **no LIMIT clause**.
**Failure scenario:** `search_receipts({root_task_id: "T", limit: 10000000})`, or `list_task_receipts({task_id: "T", include_payload: true})` on a long-lived task, loads every matching row plus full JSON payloads into memory and JSON-serialises them into one response. One request OOMs the process; the ledger is a single point of failure for the whole stack.
**Fix:** `limit = min(int(...), settings.search_max_limit)` in both, with a non-null default for `list_task_receipts`.

### F-14 — MEDIUM — Unvalidated tool arguments escape as unhandled 500s

`src/receiptgate/mcp/routes.py:208` (`int(arguments.get("limit") or ...)`) raises `ValueError` on `{"limit": "abc"}`. `routes.py:242` passes a non-integer `limit` straight into the SQL bind. `routes.py:254` passes `since` unvalidated into `stored_at >= :since` — on Postgres a non-timestamp string is a `DataError`. The `try` block at `routes.py:162` has **only** a `finally:` — no `except`. Only `submit_receipt` has local error handling (`:184-201`).
**Failure scenario:** `list_inbox({recipient_ai: "a", limit: "20"})` — a plausible client bug — produces an unhandled traceback, a 500 with no JSON-RPC error envelope, and breaks §2's "consistent error model".
**Fix:** coerce and validate all scalar args up front; wrap the dispatch in `except Exception` → JSON-RPC error envelope.

### F-15 — MEDIUM — `stored_at` is computed twice; the value returned on first write differs from the value returned on replay

`routes.py:176` — `stored_at = receiptgate_clock()` → written into the payload JSON. `ledger_v1.py:47` — `stored_at = _now_iso()` → written into the `stored_at` **column**. Two different timestamps for one receipt. `put_receipt:96` returns the column value on first write; `put_receipt:110-113` returns `existing.get("stored_at")` on replay, which comes from `get_receipt` → the **payload** value (`ledger_v1.py:260-261` only backfills from the row when the key is absent, and it never is).
**Failure scenario:** a client stores `r-1`, records `stored_at = T_col`, retries after a network blip, receives `stored_at = T_payload ≠ T_col`, and flags a ledger inconsistency. Worse for ordering: `receipt.rules.md:146` designates `stored_at` "source of truth for receipt ordering", but the sort column and the value the receipt reports are different clock reads.
**Fix:** compute once and use the same value for both the column and the payload.

### F-16 — MEDIUM — No read-path authorization: any credential holder can read any agent's inbox and any receipt

`routes.py:141` — `dependencies=[Depends(verify_api_key)]` gates the router with one global key. `routes.py:160` — `tenant_id = settings.default_tenant_id`, a constant. `list_inbox`, `get_receipt`, `list_task_receipts`, `search_receipts` all take the target `recipient_ai`/`receipt_id`/`task_id` from arguments with no check that the caller is that principal.
`receipt.store.md:424-427` says "Users can only access receipts in their `tenant_id`" — true but vacuous when every caller shares tenant `"default"`.
**Failure scenario:** CogniGate (agent-blindness required by the CorpoVellum gov-plane invariants) calls `list_inbox({recipient_ai: "agent:auditor"})` and reads the entire audit inbox including `task_body` and `outcome_text`. Nothing prevents it. Single-tenancy is a declared v1 limitation (`RECEIPTGATE_V1_EXIT_CRITERIA.md:32`); *principal-level* read isolation is not mentioned as a limitation anywhere and callers will assume it exists.
**Fix:** per-component credentials + a read check that the caller is the `recipient_ai` or holds an explicit auditor scope. At minimum, state the limitation explicitly in §10 and the README.

### F-17 — MEDIUM — Dead legacy schema with a contradictory phase enum ships and auto-applies

`schema/001_receipts.sql:8` — `CHECK (phase IN ('accepted', 'complete', 'escalate', 'cancel'))`. `schema/002_receipt_views.sql:11` — `t.phase IN ('complete', 'escalate', 'cancel')`. `schema/004_receipt_embeddings.sql:4` — `REFERENCES receipts(receipt_id) ON DELETE CASCADE`. The canonical enum is 3 values with `canceled` as a `status`. All three files are applied on startup (`db.py:69-81`, `auto_migrate_on_startup` default `true`), create tables nothing writes, and are asserted-present by `tests/test_migrations.py:34-42` — so the test suite actively defends the dead code.
**Failure scenario:** a new contributor reads `001_receipts.sql` (the file literally named "receipts") plus `receipts.put Contract.txt:66` and implements a `phase: "cancel"` emitter in another gate. Every such receipt is rejected by the v1 schema at `routes.py:178`, so the cancel path never closes anything — F-2's silent-loss mode with a validation error instead.
**Fix:** delete `001`, `002`, `004` and their `profiles/` copies, or renumber and clearly mark them `LEGACY_UNUSED`.

### F-18 — MEDIUM — `dedupe_key` is a required schema field the implementation never uses

`receipt.rules.md:170-172` — "Clients SHOULD use `dedupe_key` to prevent duplicate receipt processing". `grep -rn "dedupe" src/` → nothing outside test fixtures. Deduplication is entirely `receipt_id` + canonical hash.
**Failure scenario:** AsyncGate retries a completion after a timeout, generating a fresh ULID (correct — `receipt_id` is per-receipt) but the same `dedupe_key`. Two `complete` receipts land for one obligation. With F-2 unimplemented, both are stored, and the ledger shows a duplicate discharge.
This does satisfy Exit Criteria §7's "dedupe behavior verified (**hash computed or enforced**)" on the hash arm — but the field the canonical rules point clients at is inert and should be documented as such.

### F-19 — MEDIUM — Repo ships three contradictory "authoritative" protocol specs

`Receipt Protocol Golden.txt:349-360` — "This document is the **single source of truth** for: ReceiptGate schema, `receipts.put` contract, escalation semantics, derived inbox logic. All other documents must conform to this spec or be considered outdated." It specifies `obligation_id`, `recipient`, `created_by`, a `cancel` phase, and receiver-minted escalation with a required `body.escalation.{parent_receipt_id, child_obligation_id, from, to}`.
`receipts.put Contract.txt` specifies `POST /receipts` (REST), which `RECEIPTGATE_V1_EXIT_CRITERIA.md:28` says was removed.
The shipped implementation follows neither — it follows `LegiVellum/docs/canonical/receipt.schema.v1.json` (`task_id`, `recipient_ai`, `from_principal`, 3 phases, sender-minted escalate). `LegiVellum/shared/legivellum/models.py` agrees with the implementation.
**Failure scenario:** an integrator reads the file that declares itself authoritative, builds a receiver-minted escalation emitter with `body.escalation`, and every receipt is rejected for `additionalProperties` violations on `obligation_id`/`recipient`/`created_by`. §9 cannot lock semantics that the repo contradicts itself about.
**Fix:** move the three legacy docs to `docs/legacy/` with a header pointing at `LegiVellum/docs/canonical/`, or delete them.

### F-20 — MEDIUM — CI mypy disables the exact error class that would have caught F-5

`.mypy-ci.ini` — `disable_error_code = attr-defined,call-arg,arg-type,assignment,union-attr,...,no-untyped-def` plus `follow_imports = skip` and `check_untyped_defs = False`. `pyproject.toml` declares `[tool.mypy] strict = true`, which CI never uses. With `call-arg` enabled, `logger.info(..., receipt_id=...)` is a compile-time error.
**Fix:** re-enable `call-arg` and `arg-type` at minimum; they are the two codes that catch wrong-signature calls.

## Low / Nits

- **LOW** — `ledger_v1.py:205, 295` — `ORDER BY stored_at` only. `receipt.rules.md:157-159` requires `created_at` as the secondary sort key. Receipts sharing a `stored_at` return in arbitrary order.
- **LOW** — `ledger_v1.py:351` — chain traversal is N+1 (one round-trip per hop, up to 2048). `receipt.store.md:305-316` specifies a single recursive CTE. Postgres supports it; SQLite 3.8.3+ supports it.
- **LOW** — `routes.py:229-232` — `bootstrap` returns hardcoded `"last_10_receipts": []` and `"recent_patterns": []`. `receipt.store.md:243-247` says bootstrap must provide "Recent context (last actions)". The field is present and permanently empty, which reads as "no recent activity" rather than "not implemented".
- **LOW** — `routes.py:226` — bootstrap advertises `"capabilities": ["receipts", "audit"]` while `receipt.store.md:230` shows `["receipts", "semantic_memory", "audit"]`. Minor contract drift in a field clients may branch on.
- **LOW** — `config.py:91-94` / README:128 — `log_receipt_bodies` is declared and documented, never read (`grep` confirms). Dead privacy control.
- **LOW** — `profiles/receiptgate/schema/` duplicates `schema/001-004` byte-for-byte but is missing `005_receipts_v1.sql` — the only table actually in use. `db.py:65` only globs `schema/`, so the `profiles/` copies are dead, but they will drift and mislead.
- **LOW** — `config.py:74-78` — CORS defaults to `localhost:3000`/`8080` with `allow_credentials=True` on a service-to-service ledger that has no browser client. Unnecessary surface.
- **NIT** — `auth.py:1-5` — docstring says "Authentication for ReceiptGate **REST API**"; REST was removed (`RECEIPTGATE_V1_EXIT_CRITERIA.md:28`).
- **NIT** — `README.md:66-70` — "Terminal phases for obligation closure: `complete`, `escalate`" is stated twice in consecutive paragraphs.
- **NIT** — `RECEIPTGATE_V1_EXIT_CRITERIA.md:77` claims "Logs include correlation keys (receipt_id, task_id, recipient_ai)" — see F-5; the single such log line cannot execute.
- **NIT** — `Excellent. This is the right moment.txt` and `Mem_Test_Spec.md` sit unreferenced at repo root.

## Test Coverage Gaps

12 test files, ~1000 lines. What is genuinely covered: canonical-hash determinism and `created_at` sensitivity (`test_utils.py`), idempotent replay + collision (`test_receipts.py:63-102`, `test_mcp.py:94-118`), phase-conditional schema rules actually rejecting (`test_validation.py:104-131`), fail-closed on missing schema file (`test_validation.py:96-101`), inbox tenant scoping (`test_ledger_v1.py:33`), migrations from empty (`test_migrations.py`), auth (`test_auth.py`).

**Required regressions from Exit Criteria §7 (lines 129-139):**

| Required regression | Status |
|---|---|
| cancel emits terminal receipt and closes obligation | **MISSING**. `grep -n "cancel" tests/` → zero hits. No test ever sets `status: "canceled"`. The one terminal-closure test (`test_ledger_v1.py:6`) uses `status` absent entirely. |
| ack/progress/anomaly does NOT close obligation | **MISSING**. No test submits a non-terminal, non-`accepted` receipt. These types do not exist in the v1 phase enum, so the claim rests entirely on the enum — untested, and undocumented as the mechanism. |
| lease claim/renew/expire never triggers validation errors | N/A (AsyncGate owns leases). |
| dedupe behavior verified | **COVERED** (hash arm) — `test_receipts.py:63-102`, `test_utils.py`. The `dedupe_key` arm is untested because unimplemented (F-18). |
| terminator logic closes only on terminal receipt types | **PARTIAL**. `test_validation_v1.py:126-129` unit-tests `is_terminal_receipt` for 3 phases. No test exercises the *query* (`ledger_v1.py:157-162`) with a non-terminal receipt present, and `is_terminal_receipt` is **dead code** — `grep -rn "is_terminal_receipt" src/` shows it is never called by `list_inbox`, which reimplements the check in SQL. The tested function and the shipped logic are different code. |

**Additional gaps, each naming a finding above:**
- No test that a second `complete` on the same `task_id` is rejected (F-2).
- No test that `accepted` after a terminal receipt is rejected or at least visible (F-2). This is the silent-loss case.
- No test that agent B's `accepted` survives agent A's `complete` on a shared `task_id` (F-3). Writing this test fails today.
- No test that an `escalate` receipt reaches `escalation_to`'s inbox (F-4). Writing this test fails today.
- No test with logging at INFO (F-5). The entire suite runs at default WARNING, which is why the `TypeError` is invisible.
- No cycle test: `caused_by_receipt_id == receipt_id`, or a 2-node cycle (F-6).
- No dangling-parent test, and no test of `enforce_cause_exists` in either state (F-6).
- No test that `archived_at` on an `accepted` receipt is rejected (F-7).
- No cross-tenant test on `get_receipt`, `list_task_receipts`, `search_receipts`, `get_receipt_chain` — only `list_inbox` is tenant-tested (`test_ledger_v1.py:33`).
- No test that `recipient_ai: "NA"` / `receipt_id: "NA"` is rejected (F-10).
- No test that `search`/`list_task_receipts` limits are clamped (F-13).
- No concurrency test on `put_receipt` — the `IntegrityError` recovery path (`ledger_v1.py:124-141`) is unexercised, and SQLite tests cannot exercise it meaningfully anyway.
- `--cov-fail-under=75` on a repo where the uncovered 25% includes the concurrency recovery path and the log line that crashes.

## Cross-repo observations

1. **AsyncGate and ReceiptGate do not share a receipt model.** `LegiVellum/.standalone_code/AsyncGate/src/asyncgate/models/receipt.py:18` and `engine/core.py` build receipts around a `receipt_type` enum — `TASK_ASSIGNED`, `TASK_PROGRESS`, `RECEIPT_ACKNOWLEDGED`, `SYSTEM_ANOMALY`, `LEASE_EXPIRED`, `TASK_RESULT_READY`. The canonical schema has **no `receipt_type` property** and `additionalProperties: false`. Every AsyncGate receipt would be rejected by `routes.py:178`. This is the source of the review brief's `ack`/`progress`/`anomaly` question: those types are AsyncGate's vocabulary, and ReceiptGate has no representation for them at all — not "they safely don't close obligations", but "they cannot be recorded". The two repos need a reconciled mapping (`receipt_type` → `phase` + `metadata`) before either can claim v1 integration readiness. **This is the highest-value cross-repo action item.**
2. **`TERMINAL_RECEIPT_TYPES` does not exist anywhere in the stack.** `grep -rn "TERMINAL_RECEIPT_TYPES"` matches only the Exit Criteria Template itself (line 71). ReceiptGate implements `TERMINAL_PHASES`, which is a reasonable rename given the v1 model has phases rather than types — but every gate scored against §4 should agree on which noun it is, and DepotGate/AsyncGate use `ReceiptType` while ReceiptGate uses `phase`.
3. **ReceiptGate agrees with the LegiVellum shared library and disagrees with itself.** `LegiVellum/shared/legivellum/models.py:148-208` reimplements the phase rules identically to `receipt.schema.v1.json` — 3 phases, `canceled` as a status, `recipient_ai == escalation_to`. So the implementation is aligned with the substrate; only ReceiptGate's own three legacy docs (F-19) dissent. Recommend deleting them rather than reconciling.
4. **`LegiVellum/docs/canonical/ReceiptGate/alignment.md` states "**Aligned** with canonical contracts."** That is true of the schema file and false of the store: the canonical `receipt.indexes.sql` mandates a `parent_task_id` index for a query the implementation cannot serve, and `receipt.store.md`'s chain CTE traverses the opposite direction from the shipped tool (F-8). The alignment doc should be downgraded to "schema-aligned, store-partial" until F-8/F-11 land.
5. **Single shared API key is a stack-wide design property, not a ReceiptGate quirk.** Because every gate must write receipts, every gate holds a credential that can forge any receipt (F-1) and read every inbox (F-16). This directly contradicts the CorpoVellum "agent blindness" invariant. Whichever repo owns credential issuance should treat per-component keys as a v1 prerequisite, not hardening.
6. **`enforce_cause_exists=false` by default means no gate can rely on provenance.** Downstream consumers (InterView especially, as the read-only introspection primitive) will render chains that are silently truncated at dangling parents with no truncation marker (F-6).

## What's solid

- **The schema file is byte-identical to canonical, and validation is on the write path, not advisory.** `routes.py:177-181` applies server fields, validates, and returns `validation_failed` with per-field `{field, constraint, message}` details *before* `put_receipt`. `additionalProperties: false` therefore actually holds at the boundary. This is the thing that most often rots in an implementation, and it did not.
- **The fail-closed decision on a missing schema file is correct and well-argued.** `validation_v1.py:87-96` raises rather than returning `[]`, with a comment explaining the exact bug that motivated it, and `test_validation.py:96-101` pins the behaviour. `_schema_path()` (`validation_v1.py:27-44`) correctly handles the installed-vs-checkout layout split with a matching `force-include` in `pyproject.toml`. Someone found a real production bug here and fixed it properly, comment and regression test included.
- **Canonical-hash idempotency is correctly specified and correctly implemented.** `utils.py:22-40` sorts keys recursively with stable separators; `_canonical_payload` (`ledger_v1.py:32-36`) excludes exactly the server-assigned fields (`stored_at`, `tenant_id`) so replays are stable; the `created_at` conditional (`:41`) handles both client- and server-supplied cases. The `IntegrityError` recovery in `put_receipt:124-141` correctly re-reads and re-compares under the losing side of a concurrent-insert race, backed by a real `UNIQUE(tenant_id, receipt_id)` index (`005_receipts_v1.sql:16-17`). This is the one concurrency path that is genuinely right.
- **Every query is `tenant_id`-scoped, including the correlated subquery.** `ledger_v1.py:159` correlates `t.tenant_id = r.tenant_id` rather than relying on the outer filter — an easy thing to get wrong. All SQL is parameterised; the two f-string interpolations (`:194` `limit_clause`, `:287` `where_clause`) are built from a fixed vocabulary with values bound, so there is no injection.
- **The routing invariant is enforced in application code where the schema cannot express it**, exactly as `receipt.rules.md:240-241` requires (`validation_v1.py:69-78`), and it is tested from both sides (`test_validation_v1.py:74-121`).
- **Middleware is above the bar for a v1 service**: request-size limiting handles both `Content-Length` and streamed-body accumulation (`security_middleware.py:151-173`), the rate limiter's `X-Forwarded-For` handling is trusted-proxy-gated rather than credulous (`rate_limiter.py:261-293`), and API-key comparison uses `secrets.compare_digest` (`auth.py:54`).
- **The MetaGate bootstrap posture is right and the reasoning is written down.** `main.py:24-30` and `README.md:153-157` — bootstrap never blocks startup, explicit config always wins, "a bootstrap authority that can take the mesh down would be a hidden master". The path-based module load in `metagate_client.py:36-59` even documents why (`@dataclass` annotation resolution requires `sys.modules` registration before `exec_module`). That is a real bug someone hit and left a note about.
- **MCP naming is fully compliant** with `mcp.naming.md`: `receiptgate.*` prefix, `tools/list` + `tools/call` on `/mcp`, `.health` reserved and side-effect free, no legacy REST surface.
