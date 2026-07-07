# Development & Contributing Guide — ALOY Version 1.0

This guide is designed for engineers and contributors looking to develop, test, and maintain the ALOY codebase.

---

## 1. Testing Subsystems

ALOY maintains an automated test suite containing **233 unit, integration, and stress tests**.

### Test Directory Layout:
* `tests/test_kernel/`: Verifies event bus concurrency, service registrations, and kernel booted status.
* `tests/test_memory/`: Asserts episodic vector search correctness, SQLite-vec connection bindings, and decay merges.
* `tests/test_stress/`: Stress tests simulating high load (concurrency, SQLite locks, tool injections, memory spikes).
* `tests/test_tools/`: Validates sandbox boundaries and filesystem isolation properties.

### Running the Test Suite:
```bash
# Run all tests
python -m pytest

# Run a specific test module
python -m pytest tests/test_kernel/test_event_bus.py

# Run only stress tests
python -m pytest tests/test_stress/
```

---

## 2. Database Migrations

ALOY uses a custom lightweight migrator to manage SQLite schemas:
* **Migration Files**: Located under `database/migrations/`.
* **Lifespan Execution**: Migrations run automatically when starting the FastAPI server (`api/server.py`).
* **Creating a Migration**: Create a new file prefixed with a sequential ID (e.g., `014_new_feature.py`) containing `migrate(conn)` and `rollback(conn)` SQL statements.

---

## 3. Self-Evolution Pipeline

The self-evolution engine scans the system for improvements:
1. **Issue Detectors**: Background routines monitor repeated execution failures, semantic overlap, and missing package dependencies.
2. **Proposal Analyzer**: Synthesizes structured markdown proposals (recommending prompt enhancements or dependency installs).
3. **Execution Gate**: User approval triggers the proposal, automatically updating prompt registries or installing packages in the background.

---

*Designed and developed by Dhanush A.*
