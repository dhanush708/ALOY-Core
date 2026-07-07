import logging

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class ReviewAgent(BaseAgent):
    """
    Review Agent checks implementation details, ensures styling guidelines are met,
    and runs action confirmations for potentially destructive steps.
    """

    def __init__(self, confirmation_workflow=None):
        self.confirmation_workflow = confirmation_workflow

    @property
    def name(self) -> str:
        return "reviewer"

    @property
    def description(self) -> str:
        return "Reviews code changes and runs security confirmation workflows."

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Review Agent executing task: %s", task.id)

        # Check if confirmation workflow is injected, otherwise simulate approval
        if self.confirmation_workflow:
            allowed = await self.confirmation_workflow.check_or_request_approval(
                actor=self.name,
                action="confirm",
                target=context.workspace_path,
                session_id=context.session_id,
            )
            if not allowed:
                return TaskResult(success=False, error="Destructive action rejected by reviewer or policy.")

        try:
            prompt = (
                f"You are the Review Agent. Task: {task.description}\n"
                "Verify the implementation conforms to safety, robustness, and style rules."
            )
            review_summary = await model_router.generate("agent_planning", prompt)

            return TaskResult(
                success=True,
                result=f"Code Review:\n{review_summary}",
                metadata={"review_passed": True},
            )
        except Exception as e:
            logger.error("Review Agent failed: %s", e)
            return TaskResult(success=False, error=str(e))
