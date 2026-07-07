import os
import json
import asyncio
import tempfile
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from kernel.event_bus import EventBus
from kernel.types import Event
from tools.system import ToolSystem
from agent.types import TaskStep, ExecutionContext, TaskStatus, AgentSessionState, TaskResult
from agent.context import ExecutionContextBuilder
from agent.registry import AgentRegistry
from agent.task_queue import AgentTaskQueue
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from agent.agents.manager import ManagerAgent
from agent.agents.planner import PlannerAgent
from agent.agents.coder import CodingAgent
from agent.agents.tester import TestingAgent
from agent.agents.reviewer import ReviewAgent
from agent.agents.architect import ArchitectureAgent
from reasoning.engine import ReasoningEngine
from evolution.service import EvolutionEngine
from memory.manager import MemoryManager
from knowledge.router import KnowledgeRouter
from knowledge.doc_intelligence import DocumentationIntelligence
from project.manager import ProjectManager
from conversation.engine import ConversationEngine
from security.rollback import AdvancedRollbackEngine
from models.router import ModelRouter

@pytest_asyncio.fixture
async def db_pool(tmp_path):
    db_file = str(Path(tmp_path).resolve() / "stress_test.db")
    pool = DatabaseConnectionPool(db_file)
    await pool.start()
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    yield pool
    await pool.stop()

@pytest_asyncio.fixture
async def event_bus():
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()

@pytest.fixture
def workspace_dir(tmp_path):
    ws = Path(tmp_path).resolve() / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "src").mkdir(parents=True, exist_ok=True)
    with open(ws / "src" / "main.py", "w", encoding="utf-8") as f:
        f.write("print('initial')\n")
    return ws

# --------------------------------------------------------------------------
# 1. Planner Agent Stress & Failure Injection
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_planner_agent_failure_injection(workspace_dir):
    agent = PlannerAgent()
    task = TaskStep("t1", "s1", "planner", "Decompose", "Plan task")
    context = ExecutionContextBuilder.build("s1", "p1", "Add login form", str(workspace_dir), {})
    
    # Simulate LLM model failure / offline
    model_router = AsyncMock()
    model_router.generate.side_effect = RuntimeError("Ollama service unavailable")
    
    result = await agent.execute(task, context, AsyncMock(), model_router)
    assert result.success is False
    assert "Ollama service unavailable" in result.error

# --------------------------------------------------------------------------
# 2. Reviewer Agent Confirmation Denied
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reviewer_agent_confirmation_denied(workspace_dir):
    # Setup reviewer with mocked confirmation workflow that rejects the action
    confirmation_workflow = AsyncMock()
    confirmation_workflow.check_or_request_approval.return_value = False
    
    agent = ReviewAgent(confirmation_workflow=confirmation_workflow)
    task = TaskStep("t1", "s1", "reviewer", "Verify", "Destructive file clean")
    context = ExecutionContextBuilder.build("s1", "p1", "Goal", str(workspace_dir), {})
    
    result = await agent.execute(task, context, AsyncMock(), AsyncMock())
    assert result.success is False
    assert "action rejected by reviewer" in result.error

# --------------------------------------------------------------------------
# 3. Coding Agent Surgical Rollback & Recovery
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_coder_agent_surgical_rollback(db_pool, workspace_dir):
    snapshot_mgr = WorkspaceSnapshotManager(snapshots_dir=workspace_dir / ".snapshots")
    rollback_engine = AdvancedRollbackEngine(db_pool, snapshot_mgr)
    
    ws_path = str(workspace_dir)
    file_to_modify = workspace_dir / "src" / "main.py"
    
    # 1. Capture snapshot before modifications
    snapshot_ref = await snapshot_mgr.create_snapshot(ws_path, "session-rollback")
    
    # Record project, session, checkpoint
    with db_pool.get_write_connection() as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES ('p-roll', 'Proj', ?, 'now', 'now')", (ws_path,))
        conn.execute("INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES ('s-roll', 'p-roll', 'goal', 'executing', 'now', 'now')")
        conn.execute(
            "INSERT INTO agent_checkpoints (id, session_id, step_index, snapshot_path, state_data, created_at) VALUES ('chk-roll', 's-roll', 1, ?, '{}', 'now')",
            (snapshot_ref,)
        )
        conn.execute(
            "INSERT INTO agent_tasks (id, session_id, assigned_agent, title, description, status, retry_count, max_retries, metadata, created_at, updated_at) VALUES ('t-roll', 's-roll', 'coder', 'title', 'desc', 'done', 0, 3, ?, 'now', 'now')",
            (json.dumps({"modified_files": ["src/main.py", "src/newfile.py"]}),)
        )
        
    # 2. Modify existing file & create a new file
    with open(file_to_modify, "w", encoding="utf-8") as f:
        f.write("modified version\n")
        
    new_file = workspace_dir / "src" / "newfile.py"
    new_file.write_text("new file content\n")
    
    # Assert modifications exist
    assert file_to_modify.read_text() == "modified version\n"
    assert new_file.exists() is True
    
    # 3. Trigger Surgical Rollback for modified file
    reverted_modified = await rollback_engine.revert_single_file("s-roll", "chk-roll", str(file_to_modify))
    assert reverted_modified is True
    assert file_to_modify.read_text() == "print('initial')\n"
    
    # 4. Trigger Surgical Rollback for new file (should delete it)
    reverted_new = await rollback_engine.revert_single_file("s-roll", "chk-roll", str(new_file))
    assert reverted_new is True
    assert new_file.exists() is False

# --------------------------------------------------------------------------
# 4. Reasoning Agent Stage Publishing & Timeout
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reasoning_agent_stage_events_and_timeout(event_bus):
    model_router = AsyncMock()
    # Mock LLM stream response
    async def mock_stream(*args, **kwargs):
        yield "Step 1 reasoning"
        await asyncio.sleep(0.01)
        yield "Step 2 reasoning"
    model_router.stream = mock_stream
    model_router.generate = AsyncMock(return_value="Answer")
    
    prompt_registry = MagicMock()
    mock_template = MagicMock()
    mock_template.render.return_value = "Rendered prompt"
    prompt_registry.get.return_value = mock_template
    
    # Keep track of events received
    events_published = []
    def event_handler(event: Event):
        events_published.append(event)
    
    event_bus.subscribe("reasoning.stage.started", event_handler)
    event_bus.subscribe("reasoning.stage.completed", event_handler)
    
    reasoning = ReasoningEngine(model_router, prompt_registry, event_bus)
    await reasoning.start()
    
    # Run reasoning with mock strategy
    result = await reasoning.strategies.chain_of_thought("What is consciousness?", {}, "simple")
    assert result is not None
    
    # Allow background event bus processor to run and process the queue
    await asyncio.sleep(0.05)
    
    # Verify stage events were published
    assert len(events_published) > 0
    await reasoning.stop()

# --------------------------------------------------------------------------
# 5. Evolution Engine Proposals Database Integrity
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_evolution_engine_proposal_gate(db_pool):
    model_router = AsyncMock()
    model_router.generate.return_value = json.dumps({
        "problem": "OperationalError: table already exists",
        "evidence": "Occurred 3 times in session s12",
        "possible_solutions": ["Fix migration script"],
        "recommended_solution": "Edit migration 011",
        "affected_files": ["database/migrations/011_agent_tables.py"],
        "benefits": "Reliable migrations",
        "risks": "Database corruption",
        "implementation_plan": "- [ ] Step 1\n- [ ] Step 2"
    })
    
    # Set up plain MagicMock for tracker to avoid coroutine object iteration issues
    tracker = MagicMock()
    tracker._calls = {}
    
    evolution = EvolutionEngine(
        db_pool=db_pool,
        memory_manager=AsyncMock(),
        model_router=model_router,
        model_tracker=tracker,
        prompt_registry=AsyncMock(),
        agent_runtime=AsyncMock()
    )
    
    # Mock issue detector to return repeated failures findings
    evolution.analyzer.detector.detect_all = MagicMock(return_value={
        "repeated_failures": [{
            "agent": "coder",
            "task_title": "Write sqlite migration",
            "error_message": "OperationalError: table already exists",
            "evidence": "Occurred 3 times in session s12"
        }],
        "semantic_overlaps": [],
        "prompt_drift": [],
        "missing_packages": []
    })
    
    # 1. Run evolution scan to register proposals in database
    proposals = await evolution.run_scan()
    assert len(proposals) > 0
    
    # Verify proposal status is 'pending' in database
    db_proposals = await evolution.get_proposals("pending")
    assert len(db_proposals) > 0
    assert db_proposals[0].problem == "OperationalError: table already exists"

# --------------------------------------------------------------------------
# 6. Memory Manager Concurrency & Embeddings Recovery
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_memory_manager_embeddings_recovery(db_pool):
    # Setup memory manager with offline embeddings generator (returns 404/ConnectionError)
    memory = MemoryManager(db_pool)
    await memory.start()
    
    # Force connection error / model offline
    memory.embeddings.generate = AsyncMock(side_effect=ConnectionError("Embedding service offline"))
    
    # Retrieve should fall back gracefully to text-based FTS5 query and not raise exception
    results = await memory.retrieve("quicksort algorithm", limit=5)
    assert isinstance(results, list) # Should return list, even if empty

# --------------------------------------------------------------------------
# 7. Knowledge Router Intent Routing
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_knowledge_router_routing(db_pool):
    model_router = AsyncMock()
    doc_intel = AsyncMock()
    
    router = KnowledgeRouter(db_pool, AsyncMock(), doc_intel, model_router)
    
    from conversation.context_builder import _needs_live_search
    # Query requiring live web search
    assert _needs_live_search("What is the current NVIDIA graphics card?") is True
    # Query requiring only local model knowledge
    assert _needs_live_search("Explain recursion recursively") is False

# --------------------------------------------------------------------------
# 8. Workspace Lock & Concurrency Manager
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workspace_lock_concurrency(db_pool, event_bus, workspace_dir):
    ws_path = str(workspace_dir)
    lock_mgr = WorkspaceLockManager(db_pool, event_bus)
    
    # Acquire lock for session A
    assert await lock_mgr.acquire(ws_path, "session-a") is True
    # Concurrent acquisition attempt by session B must fail
    assert await lock_mgr.acquire(ws_path, "session-b") is False
    
    # Release lock
    await lock_mgr.release(ws_path, "session-a")
    assert await lock_mgr.is_locked(ws_path) is False

# --------------------------------------------------------------------------
# 9. Conversation Engine Event Queue
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conversation_engine_streaming(db_pool):
    memory = AsyncMock()
    model_router = MagicMock()
    
    # Mock LLM generation stream returning async iterator
    class AsyncIteratorMock:
        def __init__(self, items):
            self.items = items
            self.idx = 0
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.idx < len(self.items):
                val = self.items[self.idx]
                self.idx += 1
                return val
            raise StopAsyncIteration
            
    model_router.stream = MagicMock(side_effect=lambda *args, **kwargs: AsyncIteratorMock(["Answer ", "complete"]))
    model_router.generate = AsyncMock(return_value="Answer complete")
    
    engine = ConversationEngine(db_pool, memory, model_router)
    engine.app = MagicMock()
    
    # Initialize queue to receive events
    queue = asyncio.Queue()
    context = await engine.process_message("session-chat", "hello ALOY", event_queue=queue)
    
    # Extract streamed response from the event queue
    response_tokens = []
    while not queue.empty():
        event = queue.get_nowait()
        if event["type"] == "token":
            response_tokens.append(event["content"])
        
    assert "".join(response_tokens) == "Answer complete"

# --------------------------------------------------------------------------
# 10. Manager Agent Retries & Task Escalation
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_manager_agent_retries_and_escalation(db_pool, event_bus, workspace_dir):
    ws_path = str(workspace_dir)
    session_id = "session-retry-test"
    project_id = "proj-retry"
    
    now = datetime.utcnow().isoformat()
    with db_pool.get_write_connection() as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES (?, 'Proj', ?, ?, ?)", (project_id, ws_path, now, now))
        conn.execute("INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES (?, ?, 'Goal', 'planning', ?, ?)", (session_id, project_id, now, now))
        
    task_queue = AgentTaskQueue(db_pool)
    registry = AgentRegistry()
    lock_mgr = WorkspaceLockManager(db_pool, event_bus)
    snapshot_mgr = WorkspaceSnapshotManager()
    
    # Register planner to successfully parse initial step and transition
    planner_agent = AsyncMock()
    planner_agent.name = "planner"
    planner_agent.execute.return_value = TaskResult(
        success=True,
        result=json.dumps([
            {"id": "c1", "assigned_agent": "coder", "title": "Coder Fail", "description": "Fail", "depends_on": []}
        ])
    )
    registry.register("planner", planner_agent)
    
    # Coder agent always raises exception to test retries
    coder_agent = AsyncMock()
    coder_agent.name = "coder"
    coder_agent.execute.side_effect = RuntimeError("File write failure")
    registry.register("coder", coder_agent)
    
    # Mock debugger agent that handles escalation
    debugger_agent = AsyncMock()
    debugger_agent.name = "debugger"
    debugger_agent.execute.return_value = TaskResult(success=True, result="Fixed issue")
    registry.register("debugger", debugger_agent)
    
    # Mock completion agents
    documenter = AsyncMock()
    documenter.name = "documenter"
    documenter.execute.return_value = TaskResult(success=True)
    registry.register("documenter", documenter)
    
    learner = AsyncMock()
    learner.name = "learner"
    learner.execute.return_value = TaskResult(success=True)
    registry.register("learner", learner)
    
    manager = ManagerAgent(db_pool, task_queue, registry, lock_mgr, snapshot_mgr, event_bus)
    context = ExecutionContextBuilder.build(session_id, project_id, "Goal", ws_path, {})
    
    # Run manager (will fail on coder, retry, fail, escalate to debugger)
    try:
        await manager.run(session_id, context, AsyncMock(), AsyncMock())
    except Exception:
        pass
        
    # Check that task coder has failed and retry_count shows 3 (max_retries exhausted)
    with db_pool.get_read_connection() as conn:
        row = conn.execute("SELECT status, retry_count FROM agent_tasks WHERE assigned_agent = 'coder'", ()).fetchone()
        
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == 3 # retried 3 times (max_retries limit)
