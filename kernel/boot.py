import logging
import yaml
from pathlib import Path

from .event_bus import EventBus
from .service_registry import ServiceRegistry
from .lifecycle import LifecycleManager
from .scheduler import BackgroundScheduler
from .telemetry import Telemetry
from .recovery import ErrorRecovery
from .prompts import PromptRegistry
from .prompt_loader import PromptLoader
from .types import Event, SYSTEM_BOOT_COMPLETED
from .interfaces.tools import IToolSystem

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator

logger = logging.getLogger(__name__)

async def boot() -> ServiceRegistry:
    """System bootstrap sequence."""
    
    logger.info("Starting boot sequence...")
    
    # 1. Load configuration
    config_path = Path("config/default.yaml")
    config = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            
    # 2. Create core kernel components
    registry = ServiceRegistry()
    lifecycle = LifecycleManager()
    lifecycle.set_registry(registry)
    
    event_bus = EventBus()
    scheduler = BackgroundScheduler()
    telemetry = Telemetry()
    recovery = ErrorRecovery()
    
    # Register kernel components in registry (if they had interfaces)
    # For now, we'll just keep references to them or pass them explicitly
    # to subsystems that need them.
    
    # 3. Setup Database
    db_path = config.get("database", {}).get("path", "data/aloy.db")
    db_pool = DatabaseConnectionPool(db_path)
    
    # Wire db_pool and event_bus to telemetry
    telemetry.db_pool = db_pool
    telemetry.event_bus = event_bus
    
    migrator = Migrator(db_pool)
    
    logger.info("Running database migrations...")
    await migrator.migrate()
    
    # 4. Initialize and Load Prompts Registry
    prompts = PromptRegistry(db_pool)
    await prompts.start()
    
    prompt_loader = PromptLoader(prompts)
    await prompt_loader.load_defaults()
    
    # 5. Start kernel subsystems (Event Bus, Scheduler, Telemetry)
    # Since these are core to everything else, we start them manually before the main lifecycle manager
    await event_bus.start()
    await scheduler.start()
    await telemetry.start()
    await recovery.start()
    
    # In a full system, we would instantiate all other subsystems (Memory, Conversation, etc.)
    # Mission 6: Instantiate the real Model Router.
    try:
        from models.router import ModelRouter
        from learning.engine import LearningEngine
        from learning.stages.filter import LearningFilterStage
        from learning.stages.extraction import ExtractionStage
        from learning.stages.duplicate_detection import DuplicateDetectionStage
        from learning.stages.contradiction_detection import ContradictionDetectionStage
        from learning.stages.promotion import PromotionStage
        from memory.manager import MemoryManager
        
        ollama_url = config.get("ollama", {}).get("url", "http://localhost:11434")
        model_router = ModelRouter(ollama_url=ollama_url)
        memory_manager = MemoryManager(db_pool)
        
        # Wire Learning Engine through the real router
        learning_engine = LearningEngine(model_router, memory_manager)
        learning_engine.set_pipeline([
            LearningFilterStage(),
            ExtractionStage(model_router),
            DuplicateDetectionStage(memory_manager),
            ContradictionDetectionStage(memory_manager),
            PromotionStage(memory_manager)
        ])
        
        await learning_engine.start()
        
        # Wire it to event bus
        async def on_turn_completed(event):
            await learning_engine.schedule_learning(event.data.get("conversation_id"), event.data.get("history", []))
            
        event_bus.subscribe("conversation.turn.completed", on_turn_completed)

        # Wire Reasoning Engine
        from reasoning.engine import ReasoningEngine
        from kernel.interfaces.reasoning import IReasoningEngine
        
        reasoning_engine = ReasoningEngine(
            model_router=model_router,
            prompt_registry=prompts,
            event_bus=event_bus,
            db_pool=db_pool
        )
        await reasoning_engine.start()
        registry.register(IReasoningEngine, reasoning_engine)
        
        logger.info("Model Router, Learning Engine, and Reasoning Engine wired and started.")
    except Exception as e:
        logger.error(f"Failed to wire subsystems: {e}")


    # Mission 7: Initialize the Tool System with all 12 tools.
    try:
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

        workspace_root = config.get("workspace", {}).get("root", str(Path.cwd()))
        sandbox = Sandbox(workspace_root)
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

        registry.register(IToolSystem, tool_system)
        logger.info(f"Tool System started with {len(tool_registry.list_all_metadata())} tools registered.")

    except Exception as e:
        logger.error(f"Failed to initialize Tool System: {e}", exc_info=True)

    # 6. Start all registered subsystems
    await lifecycle.start_all()
    
    # 7. Publish Boot Event
    await event_bus.publish(Event(type=SYSTEM_BOOT_COMPLETED, data={}, source="boot"))
    
    logger.info("Boot sequence completed successfully.")
    
    return registry
