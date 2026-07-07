from database.connection import DatabaseConnectionPool
from agent.registry import AgentRegistry
from agent.task_queue import AgentTaskQueue
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from agent.agents.manager import ManagerAgent
from agent.agents.planner import PlannerAgent
from agent.agents.architect import ArchitectureAgent
from agent.agents.coder import CodingAgent
from agent.agents.tester import TestingAgent
from agent.agents.debugger import DebugAgent
from agent.agents.reviewer import ReviewAgent
from agent.agents.documenter import DocumentationAgent
from agent.agents.learner import LearningAgent


class AgentGrid:
    """
    Thin wiring layer that instantiates the 9 built-in agents and
    registers them with the central AgentRegistry.
    Contains zero execution logic.
    """

    def __init__(
        self,
        db_pool: DatabaseConnectionPool,
        task_queue: AgentTaskQueue,
        registry: AgentRegistry,
        lock_manager: WorkspaceLockManager,
        snapshot_manager: WorkspaceSnapshotManager,
        event_bus,
        confirmation_workflow=None,
        memory_manager=None,
    ):
        self.registry = registry

        # 1. Instantiate the 9 agents
        manager = ManagerAgent(
            db_pool=db_pool,
            task_queue=task_queue,
            registry=registry,
            lock_manager=lock_manager,
            snapshot_manager=snapshot_manager,
            event_bus=event_bus,
        )
        planner = PlannerAgent(memory_manager=memory_manager)
        architect = ArchitectureAgent()
        coder = CodingAgent(memory_manager=memory_manager)
        tester = TestingAgent()
        debugger = DebugAgent(memory_manager=memory_manager)
        reviewer = ReviewAgent(confirmation_workflow=confirmation_workflow)
        documenter = DocumentationAgent()
        learner = LearningAgent(event_bus=event_bus)

        # 2. Register all agents in the registry
        self.registry.register("manager", manager)
        self.registry.register("planner", planner)
        self.registry.register("architect", architect)
        self.registry.register("coder", coder)
        self.registry.register("tester", tester)
        self.registry.register("debugger", debugger)
        self.registry.register("reviewer", reviewer)
        self.registry.register("documenter", documenter)
        self.registry.register("learner", learner)
