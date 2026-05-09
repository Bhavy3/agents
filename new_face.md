PHASE 7.0 — Persistent Memory + Personal Context Runtime

MISSION
Implement a deterministic, interruption-safe persistent memory subsystem for FRIDAY.

The runtime owns memory.
The LLM NEVER directly controls persistence.

GOALS
- Persistent user memory across sessions
- Fast deterministic recall
- Strict safety validation
- Fully isolated failure handling
- Zero impact on audio/orchestrator stability

==================================================
CREATE ONLY THESE FILES
==================================================

core/
 ├── memory/
 │    ├── memory_worker.py
 │    ├── memory_store.py
 │    ├── memory_index.py
 │    ├── memory_models.py
 │    └── memory_validator.py

==================================================
DO NOT CREATE
==================================================

- vector databases
- embeddings
- semantic search
- ORM systems
- plugin systems
- retry frameworks
- dependency injection
- cloud sync
- giant abstractions
- automatic memory agents

==================================================
MEMORY MODEL
==================================================

Every memory record MUST contain:

- id
- type
- content
- created_at
- updated_at
- source
- confidence
- explicit_user_approved

Allowed memory types:

- preference
- alias
- pinned_note
- approved_fact
- conversation_summary

Use dataclasses only.
No pydantic.

==================================================
MEMORY STORAGE
==================================================

Use SQLite ONLY.

Requirements:
- single lightweight connection manager
- async-safe using asyncio.to_thread()
- graceful handling of sqlite lock errors
- degraded mode if DB corrupted
- no runtime crash propagation

Database file:
data/memory/friday_memory.db

==================================================
MEMORY VALIDATION
==================================================

Reject memory entries containing:
- passwords
- API keys
- access tokens
- SSH keys
- JWT-like strings
- dangerous shell commands
- executable blobs
- oversized payloads

Hard limits:
- max memory size
- max query size
- max summary size

Validation must be deterministic and lightweight.

==================================================
MEMORY WORKER
==================================================

Create supervised MemoryWorker.

Responsibilities:
- subscribe MEMORY_WRITE_REQUEST
- subscribe MEMORY_QUERY_REQUEST
- validate entries
- persist approved entries
- handle recall queries
- emit result events

Worker MUST NEVER block:
- audio transport
- VAD
- STT
- orchestrator
- TTS
- executor

Use bounded queues.

==================================================
EVENT CONTRACTS
==================================================

Add validated contracts for:

MEMORY_WRITE_REQUEST
MEMORY_WRITE_COMPLETED
MEMORY_QUERY_REQUEST
MEMORY_QUERY_RESULT
MEMORY_DENIED
MEMORY_FAILURE
MEMORY_CONTEXT_READY

==================================================
RECALL SYSTEM
==================================================

Deterministic ranking ONLY.

Ranking order:
1. exact match
2. recency
3. confidence

NO embeddings.
NO semantic search.

==================================================
CONTEXT INJECTION
==================================================

Memory subsystem may provide:
- short preference summaries
- pinned notes
- recent summaries

NEVER inject:
- full transcripts
- raw audio text dumps
- giant history blobs

Keep prompts compact.

==================================================
RUNTIME SAFETY
==================================================

Requirements:
- query timeout: 2s
- bounded queues
- cancellation safe
- corrupted DB isolated
- failed writes non-fatal
- restart-safe worker behavior

Memory subsystem may degrade independently while the rest of FRIDAY survives.

==================================================
METRICS
==================================================

Add runtime metrics:
- memories_stored
- recall_queries
- denied_memory_writes
- memory_db_latency_ms
- degraded_memory_mode

Expose metrics in dashboard.

==================================================
TESTS
==================================================

Create ONLY focused tests:

- validation rejection
- successful persistence
- deterministic recall ranking
- timeout handling
- corruption recovery

NO giant integration tests.
NO fake enterprise testing framework.

==================================================
CODE SIZE RULES
==================================================

IMPORTANT:
- Keep files small and readable
- Prefer simple functions
- Avoid deep inheritance
- Avoid helper explosion
- Avoid 300-line “fixes”
- Target ~100–150 lines per file
- If complexity grows:
  REDESIGN SIMPLER

==================================================
ARCHITECTURE PRINCIPLE
==================================================

FRIDAY is:
- runtime-first
- deterministic-first
- interruption-safe
- degraded-mode capable
- locally controlled

The runtime decides truth.
The LLM only suggests.