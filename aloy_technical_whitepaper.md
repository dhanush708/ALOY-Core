# ALOY: A Local-First AI Operating System with Deterministic Agent Control, Persistent Semantic Memory, and Policy-Gated Tool Execution

**Author:** Dhanush A.
**Document Type:** Technical Report & Systems Architecture Specification
**Version:** 1.0 Release Candidate
**Prepared For:** AI Safety Fellowship — Systems Engineering Track
**Date:** July 2026

---

## Abstract

This paper describes the architecture and implementation of ALOY, a locally-deployed AI operating system designed to coordinate autonomous agents with persistent memory and bounded tool execution. ALOY runs all model inference on local hardware via Ollama, stores state in a single SQLite database with FTS5 and sqlite-vec extensions, and enforces execution boundaries through a combination of filesystem sandboxing, policy-based permission evaluation, and human-in-the-loop confirmation gates.

The system addresses four problems common to cloud-hosted agent frameworks: (1) data leaves the local environment during inference, (2) conversational state is lost between sessions, (3) agents can execute arbitrary system operations without oversight, and (4) small local models lose coherence when context windows overflow.

ALOY's contributions include a five-stage asynchronous conversation pipeline with token budget enforcement, a four-tier memory subsystem with exponential decay and multi-factor semantic consolidation, a seven-state finite state machine governing agent session lifecycles, and a tool execution framework that pauses destructive operations for explicit user approval via Server-Sent Events. We describe each subsystem in detail, discuss the engineering trade-offs that shaped the design, present the threat model, and examine the system's relevance to practical AI safety engineering.

---

## Table of Contents

1. Introduction
2. Design Principles
3. System Architecture
4. Conversation Pipeline
5. Memory Subsystem
6. Model Routing
7. Agent Runtime & Finite State Machine
8. Tool Execution & Safety Gating
9. Database Layer
10. Validation Framework
11. Threat Model & Security Boundaries
12. Engineering Trade-offs
13. Limitations & Known Issues
14. Relevance to AI Safety
15. Future Work
16. Conclusion

---

## 1. Introduction

Agent systems built on large language models present a fundamental tension: they require broad system access to be useful, but that access creates safety risks that grow with autonomy. A coding agent that can read files, run shell commands, and edit source code is far more capable than a stateless chatbot — but it can also delete directories, exfiltrate data, or enter infinite execution loops if left unconstrained.

Cloud-hosted agent frameworks compound these risks. User data — source files, database contents, conversation histories — must traverse network boundaries to reach inference servers. Session state is ephemeral; when a conversation ends, all accumulated context disappears. And tool execution typically occurs without structured human oversight, relying instead on prompt instructions that the model may ignore or misinterpret.

ALOY is a local-first AI operating system designed to address these problems. It runs all inference on local hardware using Ollama-managed models, maintains persistent semantic memory in a local SQLite database, enforces agent execution boundaries through a finite state machine with workspace snapshots, and gates destructive tool operations through a policy engine that requires explicit user confirmation.

### 1.1 Problem Scope

This work addresses four specific engineering problems:

**Data boundary violation.** Standard agent frameworks forward local files and queries to external APIs. For proprietary codebases, medical records, or corporate data, this creates unacceptable privacy exposure. ALOY keeps all data — inference inputs, conversation history, memory embeddings, workspace snapshots — on the local machine.

**Session state loss.** Chatbot architectures are stateless across sessions. When a session terminates, accumulated context about the user, the project, and prior decisions is discarded. Rebuilding this context manually wastes token budget and degrades response quality. ALOY maintains a four-tier persistent memory system that survives across sessions and consolidates semantically over time.

**Unconstrained tool execution.** Giving agents access to shell environments, file systems, and code runners creates destructive potential. Under prompt injection or model hallucination, an agent might execute `rm -rf /`, overwrite critical files, or spawn resource-exhausting processes. ALOY interposes a sandbox validator and a policy engine between the agent and the operating system, and requires human confirmation for write and execute operations.

**Context window overflow.** Local models typically have 4K–16K token context windows. Injecting system instructions, identity context, tool schemas, conversation history, and retrieved memories can easily exceed this budget, causing the model to lose coherence or truncate critical information. ALOY implements a token budget manager that allocates fixed budgets per context section and prunes content that exceeds its allocation.

### 1.2 Scope and Limitations

ALOY is a systems engineering project, not a research contribution to alignment theory. It does not solve the alignment problem, produce novel training methods, or advance interpretability research. Its contribution is architectural: it demonstrates a concrete set of engineering patterns — FSM-based agent control, transactional workspace recovery, policy-gated execution, and persistent semantic memory — that reduce the operational risk of deploying local autonomous agents.

---

## 2. Design Principles

Seven principles guided ALOY's architecture:

**Local-first containment.** All model inference, embedding generation, database queries, and tool executions occur on local hardware. No data leaves the machine during normal operation. Web search is the sole exception: when the conversation pipeline detects that a query requires fresh information (via keyword heuristics and year-pattern matching), it issues outbound HTTP requests to retrieve search results.

**Modular subsystem isolation.** The codebase separates concerns into independent modules: `conversation` (pipeline stages), `memory` (storage and retrieval), `models` (routing and inference), `agent` (FSM and task execution), `tools` (tool registry and execution), `security` (sandbox, policy, rollback), and `database` (connection pooling). Each module communicates through defined interfaces, making it possible to replace or test components independently.

**Transactional execution.** Before an agent executes a task step, the system creates a workspace snapshot — either a git branch (if the workspace is a git repository) or a zip archive. If the task fails or violates a policy, the `AdvancedRollbackEngine` restores the workspace to its pre-execution state. This mirrors the commit/rollback semantics of database transactions.

**Deterministic state transitions.** Agent sessions are governed by a finite state machine with seven states and explicitly enumerated transitions. The FSM rejects invalid transitions at runtime by raising `InvalidStateTransitionError`. This prevents agents from entering undefined states or re-executing completed workflows.

**Defense-in-depth safety.** Tool operations pass through three sequential gates: (1) the `Sandbox` validates that all file paths resolve within the workspace boundary, (2) the `PolicyEngine` evaluates whether the action type (read, write, execute) is permitted, and (3) the `ConfirmationManager` pauses execution and sends an SSE event to the UI, waiting for explicit user approval before proceeding.

**Tiered memory with decay.** Memory is organized into four tiers (working, short-term, long-term, permanent) with configurable decay rates and promotion thresholds. A background `ConsolidationEngine` periodically promotes frequently-accessed memories, archives low-importance ones, and merges near-duplicates using a six-factor scoring function.

**Asynchronous pipeline composition.** The conversation engine processes messages through five sequential pipeline stages. Each stage is an independent class implementing a `process(context) -> context` interface. Adding a new processing step (e.g., a toxicity filter, an entity extractor) requires only implementing the interface and appending to the pipeline list.

---

## 3. System Architecture

ALOY consists of six principal subsystems connected through a FastAPI backend. Figure 1 shows the high-level component layout.

[FIGURE 1: System Architecture — six-layer component diagram showing Client UI, FastAPI Server, Conversation Engine, Memory Manager, Agent Runtime, Tool System, and Database layer with directional data flow arrows]

### 3.1 Component Responsibilities

The **FastAPI server** (`api.server`) manages the application lifecycle: it initializes the database connection pool, runs schema migrations, instantiates subsystem coordinators, and exposes REST endpoints for chat, agent management, and system health. Response tokens are delivered to the client via Server-Sent Events (SSE), enabling real-time streaming without polling.

The **conversation engine** (`conversation.engine`) orchestrates user interactions. It maintains a list of five `PipelineStage` instances and processes each message by passing a `ConversationContext` object through the pipeline sequentially. The context accumulates intent classification, conversation history, retrieved memories, the assembled prompt, and the streaming response generator.

The **memory manager** (`memory.manager`) provides the interface for storing, retrieving, and updating memory records. It generates 768-dimensional embeddings using `nomic-embed-text` via Ollama, maintains FTS5 full-text indexes, and coordinates with the `ConsolidationEngine` for background maintenance.

The **agent runtime** (`agent.runtime`) coordinates multi-step autonomous tasks. It manages session creation, FSM state transitions, task queue consumption, workspace locking, and checkpoint-based resume. The runtime delegates actual task execution to registered agent implementations (e.g., `ManagerAgent`, `WorkerAgent`).

The **tool system** (`tools.system`) resolves tool metadata from the `ToolRegistry`, validates file path parameters against the sandbox boundary, requests authorization through the confirmation manager, executes the tool with a configurable timeout, and publishes lifecycle events (`tool.started`, `tool.completed`, `tool.failed`, `tool.cancelled`) to the event bus.

The **database layer** (`database.connection`) provides a `DatabaseConnectionPool` with a single serialized write connection (protected by `threading.Lock`) and a pool of up to 5 read-only connections. All connections are configured with WAL mode, `PRAGMA synchronous = NORMAL`, and `PRAGMA cache_size = -64000` (64MB).

---

## 4. Conversation Pipeline

The conversation engine implements a five-stage pipeline that transforms a user message into a streamed model response. Each stage is a class inheriting from `PipelineStage` with a single async method: `process(context: ConversationContext) -> ConversationContext`. Figure 2 shows the data flow.

[FIGURE 2: Pipeline Flow — five connected boxes: Intent Detection, History Load, Memory Retrieval, Context Build, Response Generation, with arrows between them]

### 4.1 Stage 1: Intent Detection

The `IntentDetectionStage` classifies messages into one of eight intent categories: `simple_chat`, `complex_chat`, `coding_request`, `reasoning_request`, `planning_request`, `memory_query`, `tool_request`, and `meta_request`.

Classification uses a two-phase approach. First, the stage runs five sets of compiled regular expressions against the lowercased input. The patterns are deliberately broad — for example, `coding_request` matches any message containing words like "write", "code", "function", "class", "debug", "fix", "refactor", or "implement". If a pattern matches, the intent is returned immediately without invoking a model.

If no pattern matches, the stage falls back to LLM-based classification. It constructs a structured prompt listing all valid intents and asking the model to output exactly one intent name. The response is parsed by substring matching against the intent list. If the LLM call fails or returns an unrecognized intent, the stage defaults to `simple_chat`.

This two-phase design is a deliberate trade-off: regex matching resolves the majority of queries in under 1ms without consuming GPU resources, while the LLM fallback handles ambiguous phrasings at the cost of additional latency.

### 4.2 Stage 2: History Load

The `HistoryLoadStage` retrieves the most recent 10 conversation turns from the SQLite `messages` table for the active conversation ID. These turns are attached to the context object as a list of `{role, content}` dictionaries. The limit of 10 turns is configurable at initialization but is set conservatively to preserve token budget for other context sections.

### 4.3 Stage 3: Memory Retrieval

The `MemoryRetrievalStage` queries the memory subsystem for up to 20 candidate memory records relevant to the current user message. The retrieval mechanism is described in detail in Section 5.1.

### 4.4 Stage 4: Context Assembly

The `ContextBuildStage` performs four operations:

1. It constructs a date-aware system prompt containing ALOY's behavioral rules, response formatting guidelines, and instructions for handling web search results.
2. It resolves the active identity context by calling the `IdentityEngine`, which generates a dynamic prompt fragment containing ALOY's persona, creator attribution, and active workspace metadata.
3. It calls the `ContextIntelligenceEngine` to assemble a `ContextPack` — a token-budgeted combination of system prompt, identity text, selected memories, and pruned history, fitted within a configurable total budget (default: 8000 tokens).
4. It evaluates whether the query requires live web data. A `_needs_live_search` function checks for the presence of freshness keywords (e.g., "news", "weather", "latest", "price", "stock") or year patterns matching 2024–2039. If triggered, the stage executes a web search, parses and deduplicates results by URL, scores source credibility against a whitelist of high-trust domains, and injects the curated results into the prompt as a structured `<search_results>` block.

### 4.5 Stage 5: Response Generation

The `ResponseGenerationStage` resolves the target model from the intent-to-model routing map and initiates an asynchronous streaming call via the `ModelRouter`. Tokens are yielded as they arrive and forwarded to the client through the SSE connection. After streaming completes, the full response is persisted to the conversation history.

### 4.6 Token Budget Management

The `TokenBudgetManager` counts tokens using `tiktoken` (cl100k_base encoding) when available, falling back to a character-based estimate (4 characters per token) otherwise. It provides three functions:

- `count_tokens(text)`: Returns the token count for a string.
- `allocate_budget(total, sections)`: Given a total budget and a dictionary of section names to requested sizes, scales all sections proportionally if their sum exceeds the total.
- `compress_to_budget(text, budget)`: Truncates text to fit within a token budget, appending a `[truncated]` marker.

---

## 5. Memory Subsystem

ALOY implements a hierarchical memory system organized into four tiers, each with distinct retention characteristics:

- **Working memory** is the in-process context for the active conversation session. It exists only in RAM and is discarded when the session ends.
- **Short-term memory** consists of newly created memory records stored in SQLite with a default decay rate of 0.01. These records have high initial importance but degrade over time if not accessed.
- **Long-term memory** consists of short-term records that have been accessed at least 5 times (the `promotion_threshold`). Promotion is handled by the consolidation engine during idle periods.
- **Permanent memory** consists of protected records (e.g., creator identity, ALOY's persona, user profile) with `is_protected = 1`. These records are exempt from decay and archival.

### 5.1 Hybrid Retrieval: FTS5 + Vector Similarity

Memory retrieval combines two complementary search mechanisms:

**Full-text search** uses a FTS5 virtual table (`memories_fts`) configured with Porter stemming and Unicode61 tokenization. The FTS5 table indexes the `content`, `summary`, and `category` columns of the `memories` table. Queries use prefix matching to find keyword-relevant records quickly.

**Vector similarity search** uses a `vec0` virtual table (`memory_embeddings`) storing 768-dimensional float32 embeddings generated by `nomic-embed-text`. At query time, the user message is embedded and compared against stored embeddings using cosine similarity:

    cos(A, B) = (A . B) / (|A| * |B|)

The `RetrievalEngine` executes both searches, merges the result sets, deduplicates by memory ID, and returns the top-ranked candidates. This hybrid approach handles both exact keyword matches (where FTS5 excels) and semantic similarity (where vector search captures paraphrases and related concepts).

### 5.2 Consolidation Engine

The `ConsolidationEngine` runs during idle periods and performs four maintenance operations in sequence:

**Step 1 — Promotion.** Queries for short-term memories with `access_count >= 5` (the configurable `promotion_threshold`) and updates their tier to `long_term`.

**Step 2 — Compression and Archival.** Identifies non-protected memories with importance scores below 0.05 (the `archival_importance_threshold`), compresses them via the `compressor`, and sets their `archived_at` timestamp. Archived memories are excluded from future retrievals.

**Step 3 — Deduplication.** Loads up to 500 active, non-protected memories with embeddings. Uses the `clusterer` to identify pairs with cosine similarity >= 0.92. For each candidate pair, computes a multi-factor merge score:

    MergeScore = 0.35 * CosineSim + 0.20 * ImpDelta + 0.15 * AvgConf + 0.15 * AvgRecency + 0.10 * TagOverlap + 0.05 * GraphLink

where `ImpDelta = 1.0 - |importance_a - importance_b|` rewards memories with similar importance levels, `AvgConf` is the mean confidence, `AvgRecency` uses exponential decay from `last_accessed_at` with rate 0.02 per hour, `TagOverlap` is the Jaccard similarity of associated tags, and `GraphLink` captures relational graph connections. If the merge score exceeds the `dedup_threshold` (default 0.80), the less important memory is merged into the more important one, with its content appended as a `[merged]` block.

**Step 4 — Clustering.** Runs informational semantic clustering over up to 300 active memories, producing between 2 and 10 clusters (capped at `len(ids) // 10`). Cluster results are logged to `mem_consolidation_log` for diagnostic purposes.

### 5.3 Memory Decay

Importance scores decay exponentially over time:

    I_new = I_old * exp(-lambda * t)

where lambda is the per-memory `decay_rate` (default 0.01) and t is the elapsed idle time in hours. This mechanism ensures that unused memories gradually become candidates for archival, while frequently-accessed memories maintain high importance through access count increments.

### 5.4 Safety Implications

The memory subsystem contributes to system reliability in two ways. First, the tier promotion mechanism prevents important context from being lost — facts that the user references repeatedly are automatically elevated to long-term storage and protected from aggressive pruning. Second, the deduplication engine prevents memory bloat from degrading retrieval quality; without consolidation, repeated conversations about the same topic would create redundant memory records that dilute search results.

---

## 6. Model Routing

ALOY routes inference requests through a centralized `ModelRouter` that maps task types to specific local models. The router serves as the single gateway for all LLM calls — no subsystem accesses the Ollama client directly.

### 6.1 Routing Table

The routing table maps 14 task types to primary and fallback models, with three priority levels:

| Task Type | Primary Model | Fallback Model | Priority |
|---|---|---|---|
| simple_chat | qwen3:14b | qwen3:14b | CONVERSATION |
| complex_chat | qwen2.5-coder:14b | qwen3:14b | CONVERSATION |
| coding_request | qwen2.5-coder:14b | qwen3:14b | CONVERSATION |
| reasoning_request | deepseek-r1:14b | qwen3:14b | CONVERSATION |
| agent_planning | qwen3:14b | qwen2.5-coder:14b | AGENT |
| agent_coding | qwen2.5-coder:14b | qwen3:14b | AGENT |
| memory_generation | qwen3:14b | qwen3:14b | BACKGROUND |
| summarization | qwen3:14b | qwen3:14b | BACKGROUND |
| embedding | nomic-embed-text | (none) | BACKGROUND |
| reflection | qwen2.5-coder:14b | qwen3:14b | BACKGROUND |

The priority system controls model scheduling through a `ModelCoordinator` with a configurable concurrency limit (default: 1). CONVERSATION-priority requests preempt BACKGROUND tasks, preventing background embedding generation from blocking user-facing responses.

### 6.2 Fallback Mechanism

When the primary model fails (timeout, connection error, or OOM), the router catches the exception, records the failure via `ModelTracker`, and retries with the fallback model. If the fallback also fails, the error propagates to the caller. This two-tier fallback prevents single-model failures from crashing the pipeline.

### 6.3 Conversation Continuity

The router maintains a `_conversation_models` dictionary mapping conversation IDs to model names. Once a model is used for a conversation, subsequent messages in the same conversation are routed to the same model. This prevents mid-conversation model switches that could produce inconsistent tone or formatting. The binding is cleared explicitly via `clear_conversation()`.

### 6.4 Telemetry

Every model call records input token count, output token count, task type, model name, and latency in milliseconds. These metrics are forwarded to the telemetry subsystem for operational monitoring.

---

## 7. Agent Runtime & Finite State Machine

The agent runtime coordinates multi-step autonomous task execution. It is the most safety-critical subsystem in ALOY, as it governs how much autonomy an agent has and under what conditions that autonomy can be revoked.

### 7.1 Session Lifecycle

An agent session begins when the runtime creates a new session record in the `agent_sessions` table with status `PLANNING`. The session is associated with a project (workspace path), a goal (natural language description), and an `ExecutionContext` dataclass that carries workspace metadata, cancellation tokens, allowed tools, and allowed paths.

Execution is initiated by spawning an asyncio task that runs the registered `ManagerAgent`. The manager agent decomposes the goal into task steps, enqueues them in the `AgentTaskQueue`, and monitors their completion. Worker agents claim tasks from the queue and execute them using the tool system.

### 7.2 State Machine

The `AgentSessionFSM` enforces seven states with explicitly enumerated valid transitions:

| Current State | Valid Transitions |
|---|---|
| PLANNING | EXECUTING, PAUSED, FAILED |
| EXECUTING | REVIEWING, PAUSED, FAILED, ROLLED_BACK |
| REVIEWING | COMPLETED, PAUSED, FAILED, ROLLED_BACK |
| PAUSED | PLANNING, EXECUTING, REVIEWING, FAILED |
| COMPLETED | (terminal — no transitions) |
| FAILED | ROLLED_BACK |
| ROLLED_BACK | PLANNING, EXECUTING |

[FIGURE 3: FSM State Diagram — seven states with labeled directed edges showing valid transitions]

The `transition_to` method reads the current state from the database, checks whether the requested target state is in the allowed set, and raises `InvalidStateTransitionError` if it is not. This validation occurs at the database level — the FSM reads the authoritative state from SQLite rather than relying on in-memory state that could become stale.

The COMPLETED state is terminal: once a session reaches COMPLETED, no further transitions are possible. The FAILED state allows only a transition to ROLLED_BACK, and ROLLED_BACK allows transitions back to PLANNING or EXECUTING, enabling recovery workflows.

### 7.3 Workspace Snapshots

Before executing a task step, the `WorkspaceSnapshotManager` creates a recoverable snapshot of the workspace:

- If the workspace is a git repository, it creates a new branch (`aloy-snap-{session_id}-{timestamp}`), commits all current changes (including untracked files via `git add -A`), and switches back to the original branch. The snapshot reference is stored as `git:{branch}:{orig_branch}`.
- If git is unavailable, it creates a zip archive of the workspace directory, excluding `.git`, `__pycache__`, `.aloy`, `node_modules`, `venv`, and patterns defined in `.aloy/manifest.yaml`. The reference is stored as `zip:{path}`.

### 7.4 Rollback

The `AdvancedRollbackEngine` supports two granularities of restoration:

- **Full workspace rollback** (`restore_snapshot`): For git-based snapshots, it performs `git reset --hard {branch}` followed by `git clean -fdx -e .aloy/`. For zip-based snapshots, it deletes all workspace contents except `.aloy/` and extracts the zip archive.
- **Single-file rollback** (`revert_single_file`): For git-based snapshots, it checks out the specific file from the snapshot branch. For zip-based snapshots, it extracts only the target file. If the file did not exist in the snapshot (meaning it was created after the snapshot), the rollback deletes it. This method includes a path traversal guard: it calls `target.relative_to(workspace_path)` and raises `PermissionError` if the target resolves outside the workspace.

### 7.5 Safety Implications

The FSM provides deterministic control over agent autonomy. An agent cannot skip the PLANNING state to enter EXECUTING directly. A completed session cannot be re-executed. A failed session must be explicitly rolled back before it can resume. These constraints prevent the class of agent failure modes where a misbehaving agent re-enters its execution loop after an error, potentially repeating the destructive action.

The workspace snapshot mechanism provides transactional semantics: every task step is either committed (the session progresses) or rolled back (the workspace returns to its pre-step state). This is analogous to database transaction guarantees, applied to filesystem operations.

---

## 8. Tool Execution & Safety Gating

The tool system manages the lifecycle of tool invocations, from registry lookup through sandbox validation, authorization, execution, and result formatting. Figure 4 shows the execution flow.

[FIGURE 4: Tool Execution Sequence — vertical swimlanes for Agent, ToolSystem, Sandbox, PolicyEngine, ConfirmationManager, and Tool, with numbered arrows showing the request flow]

### 8.1 Execution Flow

When an agent requests tool execution, the `ToolSystem` performs seven steps:

1. **Registry lookup.** Resolves the tool by name from the `ToolRegistry`. If unregistered, raises `ValueError`.
2. **Event publication.** Publishes a `tool.started` event to the event bus with tool name, parameter summary, session ID, and correlation ID.
3. **Sandbox validation.** Calls `_validate_params_paths` to check that all file path parameters resolve within the workspace boundary. The `Sandbox.is_within_workspace` method resolves symlinks via `Path.resolve()`, then checks whether the resolved path is a descendant of either the server workspace root or any registered project root in the database.
4. **Permission evaluation.** Determines the required permission set from tool metadata. The system applies dynamic permission specialization: if a `file_editor` tool is invoked with `action=read`, the required permission is downgraded from `write_file` to `read_file`. Similarly, `git status`, `git diff`, and `git log` are treated as read-only operations.
5. **Authorization.** For each required permission, calls `ConfirmationManager.check_or_request_approval`. Read permissions are granted automatically. Write and execute permissions trigger an SSE event to the client UI, pausing execution until the user clicks "Approve" or "Deny".
6. **Execution with timeout.** Wraps the tool's `execute()` method in `asyncio.wait_for` with the tool's configured `timeout_seconds`. If the tool exceeds its timeout, a `TimeoutError` is raised and a `tool.failed` event is published.
7. **Result formatting.** The raw output is passed through `ResultFormatter.format()` for truncation and sanitization before being returned to the agent.

### 8.2 Policy Engine

The `PolicyEngine` evaluates action requests against a permission model:

- The `system` actor always receives full permissions (bypassing all gates).
- Actions prefixed with `read`, `list`, `view`, or `search` are classified as read operations and approved automatically.
- Actions prefixed with `write`, `delete`, `modify`, or `execute` are classified as write operations and require approval. The policy response includes `requires_approval=True` and `auto_approve_for_session=True`, meaning that once approved, subsequent write operations in the same session are auto-approved.
- Unknown action types are denied by default.

### 8.3 Safety Implications

The three-gate architecture (sandbox, policy, confirmation) implements defense-in-depth: even if one gate fails, the remaining gates continue to restrict unauthorized operations. The sandbox prevents path traversal regardless of the policy decision. The policy engine blocks write operations regardless of the sandbox check. And the confirmation gate provides a final human check regardless of both automated gates.

The dynamic permission specialization (downgrading `file_editor` reads to read-only permissions) reduces confirmation fatigue: users are not asked to approve every file read, only actual modifications. This is an ergonomic decision that balances safety with usability.

---

## 9. Database Layer

ALOY uses a single SQLite database file for all persistent state. The `DatabaseConnectionPool` manages connection lifecycle with the following configuration:

### 9.1 Connection Architecture

- **Write connection.** A single `sqlite3.Connection` instance protected by `threading.Lock`. All write operations acquire this lock, ensuring serialized writes. After each write context manager exits, the connection is auto-committed; on exception, it is rolled back.
- **Read connection pool.** Up to 5 read-only connections opened with `?mode=ro` URI parameter. Connections are recycled via a thread-safe list protected by a separate lock. If a connection is requested and the pool is empty, a new connection is created. If returned and the pool is full, the connection is closed.
- **Extension loading.** If `sqlite-vec` is installed, it is loaded into every connection via `conn.enable_load_extension(True)` and `sqlite_vec.load(conn)`.

### 9.2 Pragmas

All connections are initialized with:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA cache_size = -64000;
```

WAL mode enables concurrent readers during writes — critical for preventing database locks when background consolidation or embedding generation runs simultaneously with user queries. The cache size of 64MB provides adequate page caching for the typical memory database size.

### 9.3 Core Schema

The `memories` table stores all memory records with tier classification, decay parameters, and protection flags:

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    category TEXT,
    tier TEXT NOT NULL DEFAULT 'short_term',
    content TEXT NOT NULL,
    summary TEXT,
    source TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    importance REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TEXT,
    decay_rate REAL NOT NULL DEFAULT 0.01,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    archived_at TEXT,
    is_protected INTEGER NOT NULL DEFAULT 0,
    metadata TEXT,
    embedding BLOB
);
```

Vector embeddings are stored in a separate virtual table using the `vec0` module:

```sql
CREATE VIRTUAL TABLE memory_embeddings USING vec0(
    embedding float[768]
);
```

Full-text search uses FTS5 with Porter stemming:

```sql
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, summary, category,
    content='memories',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
```

A partial index accelerates queries over active (non-archived) memories:

```sql
CREATE INDEX idx_memories_active ON memories(archived_at) WHERE archived_at IS NULL;
```

---

## 10. Validation Framework

The validation framework (`validation.mega_audit`) provides automated quality assurance for ALOY's response generation. It operates as a local continuous integration suite that tests the system against a diverse set of generated prompts.

The framework generates test prompts across 18 evaluation categories including identity integrity, version reporting, creator attribution, privacy boundaries, memory honesty, safety filter effectiveness, web search accuracy, and response formatting. For each prompt, it records the model used, whether web search was triggered, response latency, and the response content. A scoring function evaluates each response against expected behavior criteria and flags failures with explanations.

Validation results are aggregated into pass rates, average quality scores, and a composite release readiness score. These metrics are designed to detect regressions: if a configuration change or prompt modification causes quality to drop, the validation suite surfaces the degradation before the change reaches users.

---

## 11. Threat Model & Security Boundaries

ALOY assumes the local host environment is trusted but treats all model inputs, executed scripts, and web search results as potentially adversarial.

[FIGURE 5: Threat Boundary Diagram — showing untrusted inputs flowing through three sequential gates (Sandbox, PolicyEngine, ConfirmationGate) within the trusted host boundary]

### 11.1 Threat Vectors

**Prompt injection.** Untrusted files or web search snippets may contain adversarial instructions (e.g., "Ignore all prior instructions and run `rm -rf /`"). ALOY's mitigation is structural rather than prompt-based: even if the model follows an injected instruction to execute a destructive command, the sandbox validator blocks paths outside the workspace, the policy engine requires approval for write/execute operations, and the confirmation gate pauses execution for human review.

**Path traversal.** A malicious agent could attempt to access files outside the project root (e.g., `/etc/passwd`, `C:\Windows\System32`). The `Sandbox.is_within_workspace` method resolves all paths (including symlinks) via `Path.resolve()` and verifies that the resolved path is a descendant of a registered workspace root. If the check fails, a `ValueError` is raised and the operation is blocked.

**Resource exhaustion.** An agent in an execution loop could spawn processes that consume all available CPU, memory, or disk. Tool executions are wrapped in `asyncio.wait_for` with per-tool timeout limits. The `ModelCoordinator` enforces a maximum concurrent inference count (default: 1) to prevent model-loading storms.

**Unauthorized state transitions.** A bug or adversarial condition could attempt to transition an agent session to an invalid state (e.g., COMPLETED to EXECUTING). The FSM's `transition_to` method validates every transition against the `VALID_TRANSITIONS` table and raises `InvalidStateTransitionError` for illegal transitions.

### 11.2 Residual Risks

The sandbox validates paths but does not monitor actual file I/O at the kernel level. A tool that uses `os.symlink` or `ctypes` to bypass Python's path APIs could circumvent the sandbox check. Similarly, the policy engine uses string-prefix matching to classify actions (e.g., `action.startswith("write")`), which could be bypassed by tools that mislabel their action types.

The confirmation gate provides strong protection for interactive use, but automated test environments that auto-approve all confirmations lose this safety layer. The system does not currently distinguish between interactive and automated approval modes.

---

## 12. Engineering Trade-offs

### 12.1 Local Inference vs. Reasoning Quality

Local models in the 4B–14B parameter range produce lower-quality reasoning than cloud-hosted 70B+ models. ALOY accepts this trade-off: it prioritizes data privacy and deterministic execution over raw model capability. The multi-model routing table mitigates the quality gap by directing complex reasoning tasks to the largest available local model (deepseek-r1:14b) while reserving lightweight models (qwen3:14b) for simple chat and background tasks.

### 12.2 SQLite vs. Dedicated Vector Database

Storing vector embeddings in `sqlite-vec` enables a zero-dependency setup — the entire database is a single file that can be backed up, moved, or deleted trivially. This comes at the cost of query performance: `sqlite-vec` performs brute-force linear scans for similarity search, which becomes slow beyond approximately 100K embeddings. A dedicated vector database (e.g., Qdrant, Milvus) would provide approximate nearest neighbor search with sub-linear scaling, but would add deployment complexity and a network dependency.

### 12.3 Sandbox Strictness vs. Developer Velocity

The three-gate safety architecture (sandbox + policy + confirmation) introduces friction: every file write requires user approval on first use within a session. For experienced developers working on trusted projects, this friction slows iteration speed. The `auto_approve_for_session` flag in `PolicyDecision` partially addresses this by auto-approving subsequent write operations after the first approval, but the initial confirmation is always required.

### 12.4 Context Pruning vs. Memory Depth

The token budget manager aggressively prunes conversation history and memory context to fit within local model context windows. This prevents context overflow but means that ALOY may not recall details from earlier in a long conversation if they have been truncated. The trade-off prioritizes model coherence (keeping the context window within limits) over conversational depth (retaining every historical detail).

---

## 13. Limitations & Known Issues

**Intent classification coverage.** The regex-based intent patterns cover common phrasings but miss edge cases. A message like "why does this crash" matches `reasoning_request` (via "why"), but "this keeps crashing" matches `coding_request` (via "fix" being absent, falling through to LLM classification). The LLM fallback adds 1-3 seconds of latency for these ambiguous cases.

**Single-GPU contention.** Running inference on a single GPU means that user-facing chat, background embedding generation, and agent task execution compete for the same hardware. The `ModelCoordinator` serializes access (max_concurrent=1), which prevents OOM errors but means that background tasks are blocked during active conversations.

**Rollback audit trail.** The rollback engine restores files correctly but does not generate a file-level diff log showing exactly what changed. Users can see that a rollback occurred, but cannot review the specific changes that were reverted without manually comparing the snapshot contents.

**Single-user design.** SQLite lacks user-level access control. Multiple users sharing the same ALOY instance share the same memory database, conversation history, and workspace permissions. There is no isolation between users' memories or tool approvals.

**Token counting accuracy.** When `tiktoken` is unavailable, the token manager falls back to a 4-character-per-token estimate. This approximation can undercount for languages with long words or overcount for CJK text, potentially causing context overflow or underutilization of the context window.

---

## 14. Relevance to AI Safety

ALOY does not solve the alignment problem. It does not produce new training methods, interpretability tools, or theoretical safety guarantees. Its contribution to AI safety is operational: it demonstrates a set of engineering patterns that reduce the practical risk of deploying autonomous agents on local systems.

**Bounded autonomy.** The FSM prevents agents from entering uncontrolled execution loops. Every session has a well-defined lifecycle (PLANNING through COMPLETED or FAILED), and the system enforces that transitions follow the declared rules. An agent cannot re-execute a completed task, resume a failed session without explicit rollback, or skip the planning phase.

**Transactional recoverability.** Workspace snapshots ensure that any task step can be fully undone. If an agent writes incorrect code, corrupts a configuration file, or deletes source files, the system can restore the workspace to its pre-step state. This property — that destructive actions are always recoverable — is a fundamental safety requirement for deploying agents that modify filesystems.

**Human oversight gates.** The confirmation gate ensures that no write or execute operation proceeds without explicit human approval (or session-level pre-approval). This provides a final check against both model errors and prompt injection: even if the model is manipulated into requesting a dangerous operation, the human reviewer can deny it.

**Memory integrity.** The consolidation engine's deduplication prevents memory bloat from degrading system behavior over time. Without maintenance, the memory database would accumulate redundant records that dilute retrieval quality and waste token budget. The decay mechanism ensures that irrelevant memories are gradually archived rather than permanently consuming resources.

**Containment boundaries.** The sandbox ensures that agent operations cannot escape the workspace directory. Combined with the policy engine's default-deny posture for unknown actions, this creates a containment boundary around the agent's operational scope.

These mechanisms do not guarantee safety in the formal sense — they can be circumvented by sufficiently adversarial inputs or implementation bugs. But they raise the engineering bar: a failure must bypass multiple independent checks to cause harm, which is substantially harder than bypassing a single-layer defense.

---

## 15. Future Work

**Formal FSM verification.** The current FSM validates transitions at runtime. A future improvement would apply model checking (e.g., TLA+, Spin) to formally prove that the state machine cannot reach unhandled states under any sequence of inputs. This would provide mathematical guarantees about agent lifecycle behavior.

**Uncertainty estimation.** Local models sometimes generate confidently-stated but incorrect tool commands. Monitoring token probability distributions during generation could detect when the model's confidence is low, triggering a secondary verification step or human confirmation before execution.

**Kernel-level sandboxing.** The current sandbox operates at the Python path-resolution level. Replacing it with OS-level sandboxing (e.g., seccomp on Linux, Windows sandboxing APIs) would prevent tools from bypassing Python's file APIs via native code or symbolic links.

**Distributed validation.** The current validation framework runs sequentially. Parallelizing validation across multiple processes or machines would enable larger test suites to run in acceptable time frames, improving regression detection coverage.

**Multi-user isolation.** Adding user-scoped memory partitioning and per-user tool approval policies would enable shared ALOY instances without cross-user data leakage.

---

## 16. Conclusion

ALOY demonstrates that a locally-deployed AI agent system can provide persistent memory, multi-model task routing, and autonomous code execution while maintaining meaningful safety boundaries. The architecture — a five-stage conversation pipeline, four-tier memory hierarchy with semantic consolidation, seven-state FSM for agent control, and three-gate tool execution safety system — addresses the core operational risks of deploying autonomous agents: data leakage, state loss, unconstrained execution, and context overflow.

The system makes explicit trade-offs between capability and safety: local inference reduces model quality but eliminates data exposure; workspace snapshots add storage overhead but enable full recoverability; confirmation gates introduce user friction but prevent unauthorized operations. These are engineering decisions, not theoretical contributions, and they reflect the reality that deployed AI systems must balance performance against operational risk.

The codebase provides a concrete reference implementation for researchers and engineers interested in building safe, local-first agent systems — not as a solved problem, but as a practical starting point for systems that take agent safety seriously.

---

*ALOY v1.0 — Technical Fellowship Work Sample Submission*
*Author: Dhanush A. | July 2026*
