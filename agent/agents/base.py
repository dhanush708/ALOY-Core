from abc import ABC, abstractmethod
from typing import Optional
from agent.types import TaskStep, ExecutionContext, TaskResult
from kernel.interfaces.tools import IToolSystem
from models.router import ModelRouter


class BaseAgent(ABC):
    """Abstract base class for all specialized agents in the ALOY runtime."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the agent (e.g. 'planner', 'coder')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of the agent's responsibilities."""
        pass

    @property
    def preferred_model(self) -> Optional[str]:
        """Optional preferred model key from routing table (Agent Model Affinity)."""
        return None

    @abstractmethod
    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system: IToolSystem,
        model_router: ModelRouter,
    ) -> TaskResult:
        """
        Execute a specific task step.
        Returns a TaskResult indicating success/failure and output.
        """
        pass

    async def can_handle(self, task: TaskStep) -> bool:
        """Determines if this agent is capable of handling the task."""
        return task.assigned_agent == self.name
