# LegiVellum System Specification
## Draft from MemoryGate Retrieval Test

**Document Status:** Draft generated from MemoryGate search queries only  
**Purpose:** Test MemoryGate's ability to provide complete architectural context  
**Gaps Marked:** `[MEMORY GAP: description]` indicates missing information

---

## Executive Summary

LegiVellum is a distributed system architecture for recursive cognition that survives time, resets, and scale. The name derives from "legible vellum" - a metaphor for the permanent receipt ledger that provides accountability across all operations.

**Core Problem Statement:** AI systems suffer from three fundamental flaws:
1. **Amnesia** - Loss of context across sessions
2. **Blocking** - Synchronous execution wastes cognitive cycles
3. **Chaos** - Uncoordinated delegation leads to runaway recursion

**Solution Architecture:** Seven specialized primitives coordinated through an immutable receipt protocol.

---

## Architectural Primitives

### 1. MemoryGate - Durable Memory & Receipt Store

**Purpose:** Passive ledger providing semantic memory and receipt storage

**Core Capabilities:**
- Semantic search across observations, patterns, concepts, documents
- Receipt storage (append-only ledger)
- Multi-tenant isolation
- Single-writer pattern (immutability enforced)

**Technical Details:**
- Backend: PostgreSQL with pgvector
- Embeddings: text-embedding-3-small (1536 dimensions)
- MCP interface: 14 tools for session management, storage, retrieval
- Deployment: memorygate.fly.dev (production)
- License: Apache 2.0, public GitHub repo

**Key Invariant:** MemoryGate is intentionally centralized for epistemic clarity. This is a deliberate design choice prioritizing understandability over maximum distribution.

**What MemoryGate Does NOT Do:**
- Push notifications
- State mutation
- Execution
- Routing decisions

[MEMORY GAP: Specific API endpoint details beyond basic MCP tool descriptions]
[MEMORY GAP: Rate limiting specifics, though Sprint 1 added 100/min config]
[MEMORY GAP: Exact PostgreSQL schema beyond mentions of receipts table]

---

### 2. AsyncGate - Execution Coordinator & Time Boundary

**Purpose:** Lease-based async execution without blocking cognitive cycles

**Core Architecture:**
- Workers poll for work (no push/spawn)
- Lease-based coordination (15min default)
- Task lifecycle: queued → leased → completed/failed/expired
- Dual-mode operation: standalone or MemoryGate-integrated

**State Machine:**
```
WAITING → LEASED → {SUCCESS, FAILURE, EXPIRED}
```

**Key Operations:**
- POST /v1/lease - Worker polling endpoint (returns 204 or task offer)
- Task acceptance via receipt emission (creates obligation)
- Lease expiry = lost authority (NOT failure, doesn't consume retry attempts)
- Orphan handling via expiry sweep

**Receipt Emission:**
- queue_task() → accepted receipt
- complete_task() → complete receipt  
- fail_task() → escalate receipt
- Retry queue for MemoryGate unavailability

**Critical Distinctions:**
- Offers are transient suggestions
- Receipts are durable commitments
- Task state is execution tracking (NOT obligation truth)
- Termination is TYPE SEMANTICS (static rules) + DB EVIDENCE (EXISTS queries)

**Architecture Decision:**
- NO process management (workers self-manage)
- NO worker registration (stateless polling)
- Coordination substrate only, not orchestrator

[MEMORY GAP: Complete REST API endpoint specifications]
[MEMORY GAP: PostgreSQL schema details for tasks table]
[MEMORY GAP: Heartbeat protocol details for V2]

**Repository:** github.com/PStryder/asyncgate  
**Recent Work:** P0-P1 security hardening complete, production-ready

---

### 3. DeleGate - Pure Planning Authority

**Purpose:** Intent decomposition without execution

**Core Doctrine:** DeleGates ONLY produce Plans. Everything else is corollary.

**Input:** Intent (natural language or structured) + context pointers  
**Output:** Plan (structured instructions) - NOTHING ELSE

**Plan Structure:**
1. **Metadata:** plan_id, delegate_id, created_at, scope, confidence, assumptions
2. **Steps:** Five types only
   - `call_worker` - Direct sync execution
   - `queue_execution` - Async via AsyncGate
   - `wait_for` - Await receipts/completions
   - `aggregate` - Request synthesis by principal
   - `escalate` - Report/decision request
3. **References:** MemoryGate inputs, AsyncGate expected outputs

**Worker Registry:**
- Self-describing MCP servers
- Dynamic capability discovery (NOT hardcoded types)
- Tool manifests with schemas, constraints, latency/cost hints
- Trust tiers: trusted, verified, sandbox, untrusted

**Fractal Composition:**
- DeleGates can delegate to other DeleGates
- Same public MCP contract at all tiers
- Parent sees child DeleGate as worker with delegation tools
- Enables arbitrary nesting depth

**Critical Invariants:**
- If it can delegate → DeleGate
- If it can only execute → Worker
- Workers CANNOT decompose or route to other workers
- Plans are ephemeral (cheap to regenerate)
- DeleGates are stateless wrt principal sessions (stateful for registry)

**Trust Model:**
- Trust is NOT transitive
- Principal trusts DeleGate ≠ auto-trust Workers
- Workers declare trust tier with crypto signatures
- DeleGates forward trust metadata in Plans
- Principal evaluates Plan before execution

**Receipt Emission:**
- MUST emit: plan_created receipt
- MAY emit: plan_escalated receipt
- MUST NOT emit: execution receipts (those belong to Workers)

**Schema Versioning:** DG-PLAN-0001 with deterministic validation

[MEMORY GAP: Complete Plan JSON schema structure]
[MEMORY GAP: Step dependency resolution algorithm details]
[MEMORY GAP: Worker matching fuzzy search implementation]

**Repository:** github.com/PStryder/LegiVellum (DeleGate folder)  
**Specification:** SPEC-DG-0000.txt (909 lines)

---

### 4. CogniGate - Bounded Cognitive Worker

**Purpose:** Safe AI execution without side effects

[MEMORY GAP: Detailed CogniGate architecture - memory mentions it exists with bounded cognition, plugin architecture, and AI client integration, but lacks comprehensive specification]

**Known Capabilities:**
- Bounded cognition execution
- Plugin architecture with permission validation
- MCP adapter registry
- Integration with AI providers

**Security Hardening:**
- Path traversal prevention (commit a56d41d)
- Arbitrary code execution blocked (commit 99e822e)
- Prompt injection sanitization (commit b0cb291)

**Rate Limiting:** 50 requests/minute (lowest of all primitives - expensive AI ops)

[MEMORY GAP: Complete cognitive execution model]
[MEMORY GAP: Plugin system architecture]
[MEMORY GAP: AI provider integration details]
[MEMORY GAP: Lease/receipt integration pattern]

---

### 5. DepotGate - Artifact Vault

**Purpose:** Matter storage with closure verification and shipping

[MEMORY GAP: Comprehensive DepotGate specification - memory confirms it exists as "matter vault for artifact staging and shipping with closure verification" but lacks detailed architecture]

**Known Function:**
- Artifact staging
- Shipping with closure checks
- Deliverable management

**Rate Limiting:** 200 requests/minute (artifact upload workload)

[MEMORY GAP: Staging area mechanics]
[MEMORY GAP: Closure verification algorithm]
[MEMORY GAP: Shipping protocol details]
[MEMORY GAP: Artifact pointer structure]
[MEMORY GAP: Storage backend configuration]

---

### 6. MetaGate - System Warden & Bootstrap Authority

**Purpose:** Non-blocking bootstrap authority providing world truth

**Core Doctrine:** MetaGate is truth, not control

**What MetaGate Provides:**
- Bootstrap authority
- Configuration distribution
- World truth to components before participation
- Metadata and policy lookups

**What MetaGate Does NOT Do:**
- Orchestrate execution
- Block on health checks
- Distribute task payloads
- Make routing decisions

[MEMORY GAP: Bootstrap protocol details]
[MEMORY GAP: Configuration schema]
[MEMORY GAP: Policy management system]
[MEMORY GAP: Metadata structure]

**Rate Limiting:** 100 requests/minute

---

### 7. InterView - Read-Only Observation

**Purpose:** Query aggregation preventing mutation

[MEMORY GAP: Detailed InterView architecture - memory confirms read-only observation layer but lacks comprehensive specification]

**Known Function:**
- Read-only data access
- Observation without mutation
- Query API for status/receipts

**Rate Limiting:** 100 requests/minute

[MEMORY GAP: Query API details]
[MEMORY GAP: Component polling patterns]
[MEMORY GAP: Aggregation strategies]

---

### 8. InterroGate - Admission Control Filter

**Purpose:** Recursion prevention and invariant enforcement

[MEMORY GAP: Comprehensive InterroGate specification - memory mentions admission filter for recursion and invariant safety but lacks detailed architecture]

**Known Function:**
- Admission control (ALLOW/DENY only)
- Recursion prevention
- Invariant enforcement
- Non-orchestrating filter

**Rate Limiting:** 1000 requests/minute (highest - high volume filtering)

[MEMORY GAP: Admission evaluation algorithm]
[MEMORY GAP: Recursion detection mechanism]
[MEMORY GAP: Policy enforcement rules]
[MEMORY GAP: Receipt routing logic]

---

## Receipt Protocol - Universal Coordination Primitive

**Purpose:** Turn time from enemy to neutral factor

### Three-Phase Protocol

**Phase 1: ACCEPTED**
- Creates obligation
- Requires non-TBD summary
- Establishes task ownership
- Immutable once written

**Phase 2: COMPLETE**
- Discharges obligation
- Requires artifact pointers OR delivery_proof
- Links to parent via caused_by
- Enables work-in-flight visibility

**Phase 3: ESCALATE**
- Creates boundary signal
- Requires escalation_to field
- New owner must explicitly accept with new task_id
- Enables hierarchical decision flow

### Receipt Structure

**Dual ID System:**
- Semantic receipt_id (human-readable)
- UUID (collision-proof)

**Core Fields:**
```json
{
  "receipt_id": "semantic-identifier",
  "uuid": "collision-proof-id",
  "task_id": "task-reference",
  "phase": "accepted|complete|escalate",
  "created_at": "ISO-8601-timestamp",
  "created_by": "principal-id",
  "caused_by": ["parent-receipt-id"],
  "recipient_ai": "owner-id"
}
```

**Chaining Semantics:**
- caused_by links receipts
- No pairing fields (async protocol)
- Relationships derived via task_id queries
- Parent linkage enforced on terminal receipts

**Locatability Enforcement:**
- Success MUST have artifacts OR delivery_proof
- Missing locatability strips parents (keeps obligation open)
- Forces producer to fix before discharge

### Receipt Routing Invariant

**Execution receipts → Owner's inbox**
**Escalation receipts → Tier above**

Pattern prevents inbox overload at top tier:
- Workers → AsyncGate → MemoryGate → Domain DeleGate inbox (execution)
- Domain DeleGate escalates → MemoryGate → Principal inbox (escalations only)

Matches human org charts: CEO sees escalations, not every task completion.

### Key Properties

1. **Temporal Resilience:** Work survives session resets
2. **Accountability Chains:** Trace to origin via caused_by
3. **Work-in-Flight Visibility:** Unpaired receipts = open obligations
4. **Complete Audit Trail:** Every action leaves immutable proof
5. **Inbox Ownership:** Receipts owned by exactly one cognitive entity

**Validation:**
- JSON Schema: receipt.schema.v1.json (331 lines)
- PostgreSQL schema with CHECK constraints
- Phase-specific conditional validations
- Python validator tool

**Storage:**
- Append-only ledger in MemoryGate
- PostgreSQL with indexes for query performance
- 64-char hash deduplication (full receipt including recipient)

[MEMORY GAP: Complete artifact_location URI scheme details]
[MEMORY GAP: delivery_proof schema specifics]
[MEMORY GAP: Escalation class taxonomy]
[MEMORY GAP: Retry queue implementation]

**Specification Files:**
- spec/receipt.schema.v1.json
- spec/receipt.rules.md (216 lines)
- spec/receipt.indexes.sql (48 lines)
- tools/validate_receipt.py (124 lines)
- examples/receipts/{accepted,complete,escalate}.json

---

## Integration Patterns

### Recursive Cognition Flow

```
Principal forms intent
    ↓
DeleGate decomposes into Plan
    ↓
Workers execute (via AsyncGate lease)
    ↓
AsyncGate holds pointers + state
    ↓
MemoryGate surfaces signal + preserves meaning
    ↓
DeleGate/Principal synthesizes + updates beliefs
    ↓
Loop repeats WITH STATE (not amnesia)
```

**Key Insight:** Separation enables independent scaling
- MemoryGate: Makes recursion persistent
- AsyncGate: Makes recursion non-blocking
- DeleGate: Makes recursion composable

### Layer Architecture

**L0:** Principal DeleGate + MemoryGate (shared truth)  
**L1:** Domain DeleGates + AsyncGate (execution coordination)  
**L2:** Workers (pure execution)

Each layer uses same contracts - fractal composition at all scales.

### Session Initialization Pattern

[MEMORY GAP: Specific bootstrap handshake sequence]
[MEMORY GAP: Configuration injection mechanism]
[MEMORY GAP: Service token authentication details]

---

## Core Invariants

### 1. Role Discriminator
**If it can delegate → DeleGate**  
**If it can only execute → Worker**

Workers cannot decompose or route to other workers.

### 2. Pure Planner Model
DeleGates only produce Plans (structured instructions).  
Schema validation rejects non-Plan outputs.

### 3. Receipt Routing
- Execution receipts → work owner's inbox
- Escalation receipts → decision maker's inbox (tier above)

### 4. Inbox Ownership
Receipts owned by exactly one cognitive entity (recipient_ai).  
No shared inbox, no competitive claiming.  
Escalation creates NEW receipt upward.

### 5. Non-Transitive Trust
Principal trusting DeleGate ≠ auto-trusting all Workers.  
Trust evaluation required at each tier.

---

## Design Principles

1. **Separation of Concerns:** Thinking / Working / Remembering cleanly divided
2. **Passivity as Strength:** MemoryGate doesn't push, DeleGate doesn't execute
3. **Epistemic Clarity over Distribution:** Centralized MemoryGate is intentional
4. **Hard Boundaries:** Architecture prevents entire classes of bugs
5. **Immutability:** Receipts append-only, state derived via queries
6. **Schema Validation:** Strict typing prevents scope creep
7. **Self-Healing:** Recovery via stateless replanning

---

## Deployment Architecture

### Current State (Sprint 1 Complete)

**Health Check Standardization:** ✓  
All 8 primitives return: `{status, service, version, instance_id}`

**Config Normalization:** ✓  
Pydantic SettingsConfigDict pattern with Field() descriptions

**Config Validation:** ✓  
@field_validator decorators for startup checks:
- Database URLs (PostgreSQL format)
- Port ranges (1-65535)
- Integration URLs (HTTP/HTTPS/redis)
- API keys (production enforcement)

**Rate Limiting:** ✓  
InMemoryRateLimiter with sliding window:
- InterroGate: 1000/min
- DeleGate/DepotGate: 200/min  
- InterView/MetaGate: 100/min
- AsyncGate: 100/min
- CogniGate: 50/min

**Authentication:**
- API key based
- allow_insecure_dev flag for development
- Production requires explicit API keys

### Deployment Platforms

**MemoryGate:** Fly.io (memorygate.fly.dev)  
**AsyncGate:** Production-ready (github.com/PStryder/asyncgate)  
**Others:** Docker-ready, MCP-compliant

[MEMORY GAP: Kubernetes deployment configurations]
[MEMORY GAP: Multi-instance coordination specifics]
[MEMORY GAP: Service mesh integration details]
[MEMORY GAP: Monitoring and observability stack]

---

## Implementation Phases

### Phase 1: Core Infrastructure
- MemoryGate receipt store ✓
- AsyncGate task coordination ✓
- Basic receipt protocol ✓

### Phase 2: Integration
- DeleGate planning layer [PARTIAL]
- Worker reference implementations [IN PROGRESS]
- Receipt chaining validation ✓

### Phase 3: Scale
- Multi-instance AsyncGate [READY]
- DepotGate artifact management [MEMORY GAP: status]
- MetaGate bootstrap distribution [MEMORY GAP: status]

### Phase 4: Production Hardening
- Security audit complete (Sprint 1) ✓
- Rate limiting deployed ✓
- Config validation active ✓
- Monitoring [MEMORY GAP: Prometheus deferred]

[MEMORY GAP: Detailed implementation timeline]
[MEMORY GAP: Migration strategies for existing systems]

---

## Repository Structure

**Primary Repositories:**
- github.com/PStryder/LegiVellum - Main documentation
- github.com/PStryder/memorygate - MemoryGate implementation
- github.com/PStryder/asyncgate - AsyncGate implementation

**Location:** F:/HexyLab/LV_stack/

**Components:**
- AsyncGate/
- CogniGate/
- DeleGate/
- DepotGate/
- InterroGate/
- InterView/
- MemoryGate/
- MetaGate/

**Documentation:**
- LegiVellum_Whitepaper.md (1415 lines)
- The Misuse Codex (security patterns)
- The Rite of the Living Substrate (operational doctrine)
- The Living Spec (framework documentation)
- RFC-0001, RFC-000X (topology rules)
- composition invariants specification

---

## MemoryGate Test Results

### Information Successfully Retrieved

**Strong Coverage:**
✓ System overview and three-flaw problem statement  
✓ Seven primitives high-level descriptions  
✓ Receipt protocol three-phase structure  
✓ AsyncGate architecture (comprehensive)  
✓ DeleGate pure planner model (comprehensive)  
✓ MemoryGate capabilities and MCP tools  
✓ Core invariants and design principles  
✓ Trust model and non-transitivity  
✓ Fractal composition pattern  
✓ Receipt routing rules  
✓ Sprint 1 security hardening details  
✓ Repository locations and structure  
✓ Deployment status

**Partial Coverage:**
△ CogniGate existence and plugin architecture (lacks detail)  
△ DepotGate artifact staging (high-level only)  
△ MetaGate bootstrap authority (concept clear, mechanics unclear)  
△ InterView read-only observation (role clear, implementation unclear)  
△ InterroGate admission control (function known, algorithm missing)

### Significant Information Gaps

**Missing Implementation Details:**
- Complete REST API endpoint specifications for most primitives
- PostgreSQL schema details beyond receipt table
- Specific MCP tool schemas and parameters
- Bootstrap handshake sequences
- Configuration injection mechanisms
- Service-to-service authentication protocols

**Missing Component Architectures:**
- CogniGate cognitive execution model
- CogniGate plugin permission system
- DepotGate closure verification algorithm
- DepotGate staging area mechanics
- InterView query aggregation strategies
- InterView component polling patterns
- InterroGate admission evaluation algorithm
- InterroGate recursion detection mechanism
- MetaGate policy management system
- MetaGate configuration schema

**Missing Operational Details:**
- Kubernetes deployment configurations
- Multi-instance coordination specifics beyond AsyncGate
- Monitoring and observability stack (Prometheus mentioned but deferred)
- Migration strategies for existing systems
- Detailed implementation timeline
- Service mesh integration patterns

**Missing Protocol Details:**
- Complete artifact_location URI scheme
- delivery_proof schema specifics
- Escalation class taxonomy
- Heartbeat protocol for AsyncGate V2
- Plan JSON schema complete structure
- Step dependency resolution algorithm
- Worker matching fuzzy search implementation

### MemoryGate Strengths

1. **Architectural Vision:** Excellent coverage of high-level design, principles, and invariants
2. **Recent Work:** Strong memory of Sprint 1 implementation (just completed)
3. **AsyncGate Detail:** Comprehensive implementation knowledge (recent focus area)
4. **DeleGate Specification:** Complete pure planner model and fractal composition
5. **Receipt Protocol:** Strong understanding of three-phase coordination primitive
6. **Cross-References:** Good tracking of repository locations and file references

### MemoryGate Weaknesses

1. **Implementation Depth:** Lacks low-level API specifications and schema details
2. **Uneven Coverage:** Some primitives (CogniGate, DepotGate, InterView, InterroGate) under-documented in memory
3. **Operational Gaps:** Missing deployment, monitoring, and operational runbook details
4. **Protocol Mechanics:** Some low-level protocol implementation details not captured

### Assessment

**MemoryGate provided sufficient context for:**
- Understanding LegiVellum's architectural philosophy
- Explaining the three-flaw problem and solution approach
- Describing primitive separation of concerns
- Detailing receipt protocol coordination
- Documenting core invariants and trust model
- Tracking recent development progress

**MemoryGate needs improvement for:**
- Complete API specifications (OpenAPI/Swagger level detail)
- Database schema documentation
- Implementation algorithm specifics
- Operational playbooks and runbooks
- Detailed protocol message formats
- Configuration management details

**Recommended MemoryGate Enhancements:**
1. Store API specifications when primitives are implemented
2. Capture schema evolution with git commit references
3. Document operational procedures as they're developed
4. Link implementation files to architectural concepts
5. Store protocol message examples with schemas
6. Track configuration templates and deployment manifests

---

## Conclusion

This specification demonstrates that MemoryGate successfully captures **architectural intent and design philosophy** but requires enhancement for **implementation-level completeness**.

**What worked:** MemoryGate excels at preserving the "why" and high-level "what" of LegiVellum. The system's purpose, principles, and primitive relationships are well-documented and retrievable.

**What needs work:** Low-level "how" details - API contracts, schemas, algorithms, deployment configurations - are either missing or incomplete in memory.

**For full system documentation**, this memory-based spec should be combined with:
- On-disk specification files (SPEC-*.txt, *.md in each component)
- OpenAPI/Swagger definitions
- Database migration scripts
- Configuration templates
- Deployment manifests

**Positive finding:** Recent work (Sprint 1) is well-captured, suggesting MemoryGate effectively records active development. Older or less-visited components (CogniGate, DepotGate, InterroGate, InterView) have sparser coverage, indicating memory density correlates with recent attention.

---

## Document Metadata

**Generated:** 2026-01-08  
**Method:** MemoryGate search queries only (no disk access)  
**Search Queries:** 7 semantic searches across observations, patterns, concepts  
**Results Processed:** ~70 memory entries  
**Coverage:** ~60-70% architectural completeness, ~30-40% implementation completeness  
**Gaps Documented:** 47 explicit `[MEMORY GAP]` markers  

**Test Conclusion:** MemoryGate successfully provides architectural context for system understanding and design discussions, but requires disk-based specifications for complete implementation guidance.

---

*End of Memory-Based Specification*
