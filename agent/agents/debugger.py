import logging
from typing import Optional

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class DebugAgent(BaseAgent):
    """
    Debug Agent reads tracebacks and test failures, diagnoses the root cause,
    and constructs new coder tasks to repair the implementation.
    """

    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager

    @property
    def name(self) -> str:
        return "debugger"

    @property
    def description(self) -> str:
        return "Analyzes logs/tracebacks and creates target coding tasks to resolve bugs."

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Debug Agent executing task: %s", task.id)

        # 1. Inspect the traceback from context or task metadata
        error_info = task.description or "No error detail provided."

        # Retrieve mistake avoidance memory
        mistakes_summary = ""
        if self.memory_manager:
            try:
                from memory.profiles import RetrievalProfile
                memories = await self.memory_manager.retrieve_with_profile(
                    query=error_info,
                    profile=RetrievalProfile.CODING,
                    limit=3,
                    extra_tags=["agent:failure", "agent:bug"],
                )
                if memories:
                    mistakes_summary = "\n[Mistake Avoidance Checklist from Past Runs]:\n" + "\n".join(
                        f"- Avoid error: {m.memory.content}" for m in memories
                    )
            except Exception as e:
                logger.warning("Failed to retrieve mistake avoidance memory: %s", e)

        prompt = (
            f"You are the Debug Agent. We have encountered the following error:\n"
            f"Error: {error_info}\n"
            f"Workspace path: {context.workspace_path}\n"
            f"{mistakes_summary}\n"
            "Analyze the failure, identify the likely root cause, and specify a correction plan."
        )

        try:
            analysis = await model_router.generate("agent_planning", prompt)
            
            # Optionally, we can dynamically add a fix-up task to the session's task queue.
            # But the Manager will route execution based on this agent's returned suggestions.
            # We output the suggestion as the result.
            return TaskResult(
                success=True,
                result=f"Debug Analysis:\n{analysis}",
                metadata={"root_cause": "Identified in summary"},
            )
        except Exception as e:
            logger.error("Debug Agent failed: %s", e)
            return TaskResult(success=False, error=str(e))
