# Three-Layer Storage Architecture for LegiVellum Coordination
## Concept Document for Hexy Discussion

### The Problem

LegiVellum's coordination relies on three core data structures - receipts, plans, and tasks - that form complex webs of relationships. These relationships enable critical system behaviors:

- Receipts chain through `caused_by` to show obligation lineage
- Plans decompose into steps with dependencies that must be validated
- Tasks spawn other tasks and link to receipts that discharge their obligations
- All three structures reference each other: receipts point to tasks, tasks reference plans, plans generate receipts

Current flat storage makes these relationships implicit - buried in JSON fields requiring recursive queries and complex joins. We need explicit, traversable structure for validation, visualization, and debugging, while maintaining semantic search capabilities for pattern detection and fuzzy matching.

### Proposed Solution: Three-Layer Architecture

Rather than choose between relational, graph, or vector storage, we use all three - each optimized for its specific purpose, with the canonical text as the single source of truth.

**Layer 1: Canonical Text Storage (PostgreSQL)**
Immutable append-only records. Source of truth for audit and compliance.

**Layer 2: Knowledge Graphs (PostgreSQL or Neo4j)**
Explicit relationship edges extracted from canonical data. Structural validation and traversal.

**Layer 3: Vector Embeddings (PostgreSQL + pgvector)**
Semantic search duplicates enabling pattern detection and fuzzy matching.

### Layer 1: Canonical Text Storage

**Receipts Table:**
```sql
CREATE TABLE receipts (
    uuid UUID PRIMARY KEY,
    receipt_id TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('accepted', 'complete', 'escalate')),
    task_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    recipient_ai TEXT NOT NULL,
    body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```

**Plans Table:**
```sql
CREATE TABLE plans (
    plan_id TEXT PRIMARY KEY,
    delegate_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```

**Tasks Table:**
```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    created_by TEXT NOT NULL,
    payload JSONB NOT NULL,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```

These tables hold complete, immutable records. Nothing is ever deleted or modified. This is the audit trail, the compliance layer, the ground truth.

### Layer 2: Knowledge Graphs

Three separate but intersecting graphs derived from canonical data:

**Receipt Graph:**
- **Nodes:** Individual receipts (UUID as node ID)
- **Edges:**
  - `CAUSED_BY`: Parent receipt → child receipt (from receipt.caused_by field)
  - `COMPLETES`: Receipt → task (from receipt.task_id when phase=complete)
  - `ESCALATES_TO`: Receipt → recipient (from receipt.escalation_to when phase=escalate)
  - `ACCEPTED_BY`: Receipt → worker (from receipt.recipient_ai when phase=accepted)

**Plan Graph:**
- **Nodes:** Plans and individual steps
- **Edges:**
  - `HAS_STEP`: Plan → step (plan decomposition)
  - `DEPENDS_ON`: Step → step (from step dependencies)
  - `DELEGATES_TO`: Step → plan (when step type=queue_execution points to sub-plan)
  - `USES_WORKER`: Step → worker_id (when step type=call_worker)

**Task Graph:**
- **Nodes:** Tasks (task_id as node ID)
- **Edges:**
  - `SPAWNED_BY`: Task → parent task (from task creation context)
  - `ASSIGNED_TO`: Task → worker (from lease assignment)
  - `PRODUCES`: Task → artifact pointers (from completion receipts)
  - `DISCHARGED_BY`: Task → receipt (terminal receipt that closes obligation)

**Graph Intersections:**
- Receipt.task_id links receipt graph to task graph
- Plan.expected_outputs links plan graph to task graph
- Task completion generates receipt, linking task graph back to receipt graph

### Layer 3: Vector Embeddings

All canonical text content (receipt bodies, plan descriptions, task payloads) gets embedded into vector space using text-embedding-3-small (1536 dimensions).

**Embeddings Table:**
```sql
CREATE TABLE embeddings (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL, -- 'receipt', 'plan', 'task'
    source_id TEXT NOT NULL,   -- UUID, plan_id, or task_id
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ON embeddings USING ivfflat (embedding vector_cosine_ops);
```

Semantic search queries can now find "things like this" across all three structures without needing exact field matches.

### Query Patterns Enabled

**Structural Queries (Graph Layer):**

"Show complete obligation chain for task X":
```cypher
MATCH (t:Task {task_id: 'X'})<-[:COMPLETES]-(r:Receipt)
      <-[:CAUSED_BY*]-(ancestors:Receipt)
RETURN ancestors
```

"Is this plan's dependency graph acyclic?":
```cypher
MATCH (p:Plan {plan_id: 'Y'})-[:HAS_STEP]->(s:Step)
MATCH path = (s)-[:DEPENDS_ON*]->(s)
RETURN path // should return empty
```

"Who's responsible for this work?":
```cypher
MATCH (t:Task {task_id: 'Z'})<-[:COMPLETES]-(r:Receipt)
      -[:ACCEPTED_BY]->(worker)
RETURN worker.recipient_ai
```

**Semantic Queries (Vector Layer):**

"Find receipts related to authentication failures":
```sql
SELECT source_id, similarity
FROM embeddings
WHERE source_type = 'receipt'
ORDER BY embedding <=> encode_text('authentication failure')
LIMIT 10;
```

"Which plans are similar to this migration?":
```sql
SELECT p.plan_id, e.similarity
FROM plans p
JOIN embeddings e ON e.source_id = p.plan_id
WHERE e.source_type = 'plan'
ORDER BY e.embedding <=> (SELECT embedding FROM embeddings 
                           WHERE source_id = 'migration-plan-123')
LIMIT 5;
```

**Canonical Queries (Text Layer):**

"Give me complete receipt for audit":
```sql
SELECT * FROM receipts WHERE uuid = 'abc-123';
```

**Hybrid Queries (All Three):**

"Find tasks similar to this failure pattern, show their discharge receipts":
1. Vector search finds similar tasks
2. Graph traversal finds DISCHARGED_BY edges
3. Text layer returns full receipt content

### Benefits

**Validation Becomes Structural:**
- Cycle detection in plan dependencies = graph cycle detection
- Receipt chain integrity = graph connectivity check
- Obligation discharge verification = graph reachability query

**Debugging Becomes Visual:**
- Export subgraph for any task/receipt/plan
- Render as visualization
- See exactly where coordination failed

**Pattern Detection Works:**
- "Show me all tasks that failed similarly to this one"
- "Find plans that use similar worker combinations"
- Vector search across actual operational data

**Audit Trail Preserved:**
- Canonical text layer never changes
- Graphs can be rebuilt from scratch if needed
- Embeddings can be regenerated with better models

**Performance Optimization:**
- Graph queries O(edges) not O(n²) joins
- Vector search uses IVF indexes (fast approximate nearest neighbor)
- Canonical layer only accessed when full content needed

### Implementation Considerations

**Consistency:**
- Canonical layer writes first (source of truth)
- Graph/vector updates asynchronous (eventual consistency acceptable)
- Graph edges derived deterministically from canonical fields

**Rebuild Capability:**
- Graphs can be completely regenerated from canonical layer
- Embeddings can be regenerated with improved models
- Canonical layer is sufficient for system operation

**Query Routing:**
- Application layer decides which storage to query
- Structural questions → graph
- Semantic questions → vector
- Audit/compliance → canonical text

This architecture makes implicit relationships explicit, enables powerful queries without sacrificing immutability, and provides multiple perspectives on the same underlying coordination data.
