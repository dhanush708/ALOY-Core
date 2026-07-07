import logging
from typing import Optional

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class ArchitectureAgent(BaseAgent):
    """
    Architecture Agent maps out workspace signatures, identifies boundaries,
    and locates modules that are relevant to the implementation plan.
    """

    @property
    def name(self) -> str:
        return "architect"

    @property
    def description(self) -> str:
        return "Maps workspace signatures and identifies boundaries and affected modules."

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Architecture Agent executing task: %s", task.id)

        # 1. Run workspace inspection using the file editor tool (read workspace files or inspect structure)
        # Note: All actions must go through tool_system
        tool_context = {
            "session_id": context.session_id,
            "actor": self.name,
        }

        try:
            # Inspect workspace root or key files to find existing modules
            # For testing and simple flows, we can use model_router to summarize the analysis
            prompt = (
                f"You are the Architecture Agent. Task: {task.description}\n"
                f"Workspace path: {context.workspace_path}\n"
                f"Goal: {context.goal}\n"
                "Explain the project structure, locate affected files, and specify where new files "
                "or edits should go. Write a clear technical outline."
            )
            
            summary = await model_router.generate("agent_planning", prompt)

            return TaskResult(
                success=True,
                result=summary,
                metadata={"inspected_paths": [context.workspace_path]},
            )
        except Exception as e:
            logger.error("Architecture Agent failed: %s", e)
            return TaskResult(success=False, error=str(e))
