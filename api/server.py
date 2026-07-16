from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sys
import asyncio
from kernel.profiler import profiler
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# DEPLOYMENT PATH RESOLUTION
#
# In a PyInstaller frozen build, CWD is unreliable (set by the OS, not ALOY).
# All READ paths must resolve from sys._MEIPASS (the bundle extraction dir).
# All WRITE paths must resolve from %APPDATA%\ALOY\ (guaranteed writable).
# ══════════════════════════════════════════════════════════════════════════════

FROZEN = getattr(sys, "frozen", False)

# Write paths — always in user's AppData (set by run.py on startup, or compute here)
_data_dir_env = os.environ.get("ALOY_DATA_DIR")
_app_data = Path(_data_dir_env) if _data_dir_env else (
    Path(os.environ.get("APPDATA", Path.home())) / "ALOY" / "data"
)
_app_data.mkdir(parents=True, exist_ok=True)
DB_PATH  = str(_app_data / "aloy.db")
LOCK_FILE = str(_app_data / "running.tmp")

# Read paths — bundled assets from _MEIPASS when frozen, source tree in dev
if FROZEN:
    STATIC_DIR = Path(sys._MEIPASS) / "static"
else:
    STATIC_DIR = Path(__file__).parent.parent / "static"


from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from conversation.engine import ConversationEngine
from project.manager import ProjectManager

# Kernel & Security & Tools
from kernel.event_bus import EventBus
from models.router import ModelRouter
from security.sandbox import Sandbox
from security.policy import PolicyEngine
from security.audit import AuditLogger
from security.confirmation import ConfirmationWorkflow
from tools.registry import ToolRegistry
from tools.system import ToolSystem
from tools.impl import (
    FileEditorTool,
    TerminalTool,
    PythonRunnerTool,
    GitTool,
    BrowserTool,
    WebSearchTool,
    PDFReaderTool,
    ImageReaderTool,
    SQLiteTool,
    DockerTool,
    RunnerTool,
    DiffEngineTool,
)

# Agent Core
from agent.task_queue import AgentTaskQueue
from agent.registry import AgentRegistry
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from agent.journal import ExecutionJournalWriter
from agent.metrics import RuntimeMetricsCollector
from agent.grid import AgentGrid
from agent.runtime import AgentRuntime

# Routers
from api.routes.conversation import router as conversation_router
from api.routes.project import router as project_router
from api.routes.agent import router as agent_router
from api.routes.security import router as security_router
from api.routes.telemetry import router as telemetry_router
from api.routes.knowledge import router as knowledge_router, doc_router
from api.routes.evolution import router as evolution_router
from api.routes.memory import router as memory_router
from api.routes.profile import router as profile_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
db_pool = None
memory_manager = None
conversation_engine = None
project_manager = None
agent_runtime = None
telemetry = None
doc_intelligence = None
knowledge_router_engine = None
evolution_engine = None
identity_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, memory_manager, conversation_engine, project_manager, agent_runtime, telemetry, doc_intelligence, knowledge_router_engine, evolution_engine, identity_engine
    
    import time
    lifespan_start = time.perf_counter()

    # 1. Initialize DB
    db_init_start = time.perf_counter()
    db_pool = DatabaseConnectionPool(DB_PATH)
    await db_pool.start()
    app.state.db_pool = db_pool
    profiler.record("Database init", profiler.get_duration(db_init_start))
    
    # Check for unexpected exit lockfile before overwriting it
    app.state.unexpected_exit = False
    try:
        if os.path.exists(LOCK_FILE):
            app.state.unexpected_exit = True
            logger.warning("ALOY detected a previous unexpected exit / crash.")
        with open(LOCK_FILE, "w") as f:
            f.write("active")
    except Exception as e:
        logger.warning(f"Lockfile initialization failed: {e}")

    
    # 2. Migrate
    migrator = Migrator(db_pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    event_bus = EventBus()
    await event_bus.start()
    app.state.event_bus = event_bus

    
    from kernel.telemetry import Telemetry
    telemetry = Telemetry(db_pool, event_bus)
    await telemetry.start()
    app.state.telemetry = telemetry
    
    model_router_start = time.perf_counter()
    model_router = ModelRouter(telemetry=telemetry)
    profiler.record("Model routing init", profiler.get_duration(model_router_start))
    
    # 4. Initialize Memory
    memory_init_start = time.perf_counter()
    memory_manager = MemoryManager(db_pool, telemetry=telemetry)
    await memory_manager.start()
    app.state.memory_manager = memory_manager
    profiler.record("Memory init", profiler.get_duration(memory_init_start))
    
    # Initialize Identity Engine
    from identity.engine import IdentityEngine
    identity_engine = IdentityEngine(db_pool, memory_manager)
    await identity_engine.initialize_if_needed()
    app.state.identity_engine = identity_engine
    
    # 5. Initialize Project Manager
    project_manager = ProjectManager(db_pool)
    app.state.project_manager = project_manager
    
    # 6. Initialize Conversation Engine (model_router must be available first)
    conversation_engine = ConversationEngine(
        db_pool,
        memory_manager,
        model_router=model_router,
        identity_engine=identity_engine
    )
    conversation_engine.app = app
    app.state.engine = conversation_engine


    # 7. Initialize Security & Tool System
    sandbox = Sandbox(str(Path.cwd()), db_pool=db_pool)
    policy_engine = PolicyEngine(db_pool)
    audit_logger = AuditLogger(db_pool)
    confirmation = ConfirmationWorkflow(policy_engine, audit_logger, db_pool)
    await confirmation.start()

    tool_registry = ToolRegistry()
    for tool_cls in [
        FileEditorTool,
        TerminalTool,
        PythonRunnerTool,
        GitTool,
        BrowserTool,
        WebSearchTool,
        PDFReaderTool,
        ImageReaderTool,
        SQLiteTool,
        DockerTool,
        RunnerTool,
        DiffEngineTool,
    ]:
        tool_registry.register(tool_cls())

    tool_system = ToolSystem(tool_registry, sandbox, confirmation, event_bus)
    await tool_system.start()
    app.state.tool_system = tool_system


    # 8. Initialize Agent Subsystem
    task_queue = AgentTaskQueue(db_pool)
    agent_registry = AgentRegistry()
    lock_manager = WorkspaceLockManager(db_pool, event_bus)
    snapshot_manager = WorkspaceSnapshotManager()
    metrics_collector = RuntimeMetricsCollector()
    journal_writer = ExecutionJournalWriter(db_pool, metrics_collector)

    # Initialize Backup and Rollback Managers
    from database.backup import DatabaseBackupManager
    from security.rollback import AdvancedRollbackEngine
    app.state.backup_manager = DatabaseBackupManager("data/aloy.db")
    app.state.rollback_engine = AdvancedRollbackEngine(db_pool, snapshot_manager)

    # Grid wires the 9 agents
    agent_grid = AgentGrid(
        db_pool=db_pool,
        task_queue=task_queue,
        registry=agent_registry,
        lock_manager=lock_manager,
        snapshot_manager=snapshot_manager,
        event_bus=event_bus,
        confirmation_workflow=confirmation,
        memory_manager=memory_manager,
    )

    agent_runtime = AgentRuntime(
        db_pool=db_pool,
        registry=agent_registry,
        task_queue=task_queue,
        lock_manager=lock_manager,
        snapshot_manager=snapshot_manager,
        journal_writer=journal_writer,
        metrics_collector=metrics_collector,
        project_manager=project_manager,
        model_router=model_router,
        tool_system=tool_system,
        event_bus=event_bus,
    )
    app.state.agent_runtime = agent_runtime
    
    # 9. Initialize Documentation Intelligence & Knowledge Router
    from knowledge.doc_intelligence import DocumentationIntelligence
    from knowledge.router import KnowledgeRouter
    doc_intelligence = DocumentationIntelligence(db_pool, memory_manager, model_router)
    app.state.doc_intelligence = doc_intelligence
    
    knowledge_router_engine = KnowledgeRouter(db_pool, memory_manager, doc_intelligence, model_router)
    app.state.knowledge_router = knowledge_router_engine
    
    # 10. Initialize Prompt Registry & Evolution Engine
    from kernel.prompts import PromptRegistry
    from evolution.service import EvolutionEngine
    prompt_registry = PromptRegistry(db_pool)
    await prompt_registry.start()
    app.state.prompt_registry = prompt_registry
    
    evolution_engine = EvolutionEngine(
        db_pool=db_pool,
        memory_manager=memory_manager,
        model_router=model_router,
        model_tracker=model_router.tracker,
        prompt_registry=prompt_registry,
        agent_runtime=agent_runtime
    )
    await evolution_engine.start()
    app.state.evolution_engine = evolution_engine
    
    logger.info("ALOY V2 Server with Agent Runtime and Evolution Engine started.")
    
    profiler.record("FastAPI startup", profiler.get_duration(lifespan_start))
    yield
    
    logger.info("Shutting down ALOY V2 Server...")
    if evolution_engine:
        await evolution_engine.stop()
    if telemetry:
        await telemetry.stop()
    await tool_system.stop()
    await confirmation.stop()
    await event_bus.stop()
    await memory_manager.stop()
    await db_pool.stop()


    # Clean up lockfile on clean exit
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception as e:
        logger.warning(f"Lockfile cleanup failed: {e}")



def cleanup_lockfile():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Cleaned up lockfile on shutdown signal.")
    except Exception as e:
        logger.warning(f"Failed to clean up lockfile on shutdown signal: {e}")

def register_signal_handlers():
    import signal
    def handle_signal(sig, frame):
        logger.info(f"Received exit signal: {sig}")
        cleanup_lockfile()
        sys.exit(0)

    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, handle_signal)
        except ValueError:
            pass
    try:
        signal.signal(signal.SIGTERM, handle_signal)
    except ValueError:
        pass

register_signal_handlers()

app = FastAPI(title="ALOY V2", lifespan=lifespan)

# Include routes
app.include_router(conversation_router)
app.include_router(project_router)
app.include_router(agent_router)
app.include_router(security_router)
app.include_router(telemetry_router)
app.include_router(doc_router)
app.include_router(knowledge_router)
app.include_router(memory_router)
app.include_router(evolution_router)
app.include_router(profile_router)

# User-friendly global exception handler
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception captured: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "ALOY encountered an internal system error. Please retry or restart the application."}
    )

# Mount static files from the correct location (bundle dir in production, source tree in dev)
if not STATIC_DIR.exists():
    logger.warning(f"Static directory not found at {STATIC_DIR} — UI will not load.")
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")



@app.get("/")
async def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}
