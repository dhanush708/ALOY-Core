# Release Notes — ALOY Version 1.0.0

ALOY is an advanced local-first AI operating system that runs completely offline on your local hardware. This document outlines the key features, enhancements, performance metrics, bug fixes, and known issues for the official v1.0.0 release.

---

## 🌟 Key Features & Architecture

### 1. Event-Driven Microkernel Core
ALOY is built around an **asynchronous event bus** that decouples all subsystems (Memory, Agent Runtime, Security, Knowledge Router). Subsystems communicate concurrently by publishing and subscribing to event topics, preventing main I/O loops from blocking during heavy background computation.

### 2. Autonomous Agent Grid FSM
The Agent Grid is ALOY's autonomous software development runtime. Instead of executing linear chains of LLM prompts, ALOY coordinates a Finite State Machine (FSM) composed of specialized cooperative agents:
- **Planner**: Decomposes user goals into structured checklists.
- **Coder**: Writes implementations.
- **Tester**: Automatically writes and runs unit tests.
- **Debugger**: Analyzes stack traces and refactors code until tests pass.
- **Documenter**: Updates documentation and READMEs.
- **Learner**: Consolidates technical insights from successful runs.

---

## 🚀 Major Improvements in v1.0.0

### 1. Search System (Upgraded Retrieval Pipeline)
The web search mechanism has been upgraded to a production-grade, highly concurrent semantic retrieval pipeline:
- **Semantic Search Gating**: Uses heuristics and a fast local classifier to determine if a query requires live web data, preventing redundant search calls for static queries.
- **LLM Query Rewriting**: Generates 2-3 short, optimized query variations to maximize search matches.
- **Concurrent Multi-Search**: Executes the optimized queries in parallel using DuckDuckGo HTML scraping, resolving in under 2 seconds.
- **Multi-Factor Scoring & Ranking**: Evaluates base authority, temporal freshness, query relevance, and applies a **+15 points Official Source Bonus** (e.g. for official documentations and source repositories).
- **Automated Query Retries**: Broadens search queries up to 3 times on empty results.
- **Follow-up Continuity & Topic Drift**: Detects if follow-up queries are on the same topic, reusing prior search contexts without redundant network searches.
- **Hallucination Protection**: Overwrites search failures with: `"I couldn't verify this information from reliable sources."` and prevents training cutoff or LLM limitation phrasing.

### 2. Memory System
- **Hybrid Retrieval**: Queries vector embeddings alongside exact keyword matches.
- **Reciprocal Rank Fusion (RRF)**: Merges text and vector search results to calculate a unified relevancy score:
  $$\text{RRF Score} = \frac{1}{60 + \text{Rank}_{\text{FTS}}} + \frac{1}{60 + \text{Rank}_{\text{Vector}}}$$
- **Decay & Recency Multipliers**: Integrates memory decay and importance weighting to dynamically calculate final scores.
- **Consolidation**: Runs background routines to consolidate episodic events and check for contradictions, merging or updating memories automatically.

### 3. Agent System
- **Parallel Task Scheduler**: Executes up to 4 concurrent worker tasks based on a dynamic dependency graph (`depends_on`).
- **Progress & Dynamic ETA**: Calculates session completion percentage and dynamically estimates completion ETA using average task execution durations.
- **Git State Checkpoint & Rollback**: Seeds automated zip backups and git state checkpoints before destructive actions, enabling one-click surgical rollback to a previous state if tests fail.

### 4. Validation Framework
- **531 Passed Pytest Cases**: Comprehensive unit, integration, and stress tests executed successfully.
- **Ollama Detection**: Automatic health check verifying model routing and local hardware availability on startup.
- **Installer verification**: Verifies SQLite extensions (`sqlite-vec`), database schemas, and first-run assets.

---

## 🛠️ Bug Fixes

- **Brittle Heuristic Gating**: Fixed conversational queries (like *"Did NVIDIA announce anything?"*) failing to trigger web search.
- **Missing Concurrency**: Fixed sequential search crawler execution causing latency spikes.
- **Mock Type Errors**: Fixed `generate` method calls throwing TypeErrors under test environments when using simple mocks.
- **Thread Drift & Continuity**: Fixed search metadata losing context over conversation history reloads.
- **Hallucination Phrase Overflow**: Fixed search failures outputting standard LLM cutoff notices.

---

## ⚠️ Known Issues

- **VRAM Constraints**: Large models require 8+ GB VRAM. Users with lower VRAM must map smaller model variants (e.g., 7B parameters) in model configuration settings.
- **Windows Only Installer**: Native installer executable is currently constrained to Windows 10/11 environments.
- **Workspace Locking**: Active agent sessions lock the workspace path to a single goal at a time to prevent concurrent editing conflicts.

---

## 📥 Upgrade Notes

This is the initial production v1.0.0 release. No upgrade path from previous versions applies. Ensure Ollama is installed and running, then pull the following models:
```bash
ollama pull qwen3:14b
ollama pull qwen2.5-coder:14b
ollama pull deepseek-r1:14b
ollama pull nomic-embed-text:latest
```
