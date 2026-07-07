import logging

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class TestingAgent(BaseAgent):
    """
    Testing Agent generates unit/integration tests and executes them
    strictly via the ToolSystem's test_runner tool.
    """

    @property
    def name(self) -> str:
        return "tester"

    @property
    def description(self) -> str:
        return "Generates and runs tests for verification via the Tool System."

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Testing Agent executing task: %s", task.id)

        tool_context = {
            "session_id": context.session_id,
            "actor": self.name,
        }

        # 1. First run test suite via tool system
        try:
            test_path = task.metadata.get("test_path") or ""
            options = task.metadata.get("options") or ["-v"]

            run_res = await tool_system.execute(
                "test_runner",
                {
                    "path": test_path,
                    "options": options,
                },
                tool_context,
            )

            # Check exit code or outcomes in result
            if "Exit Code: 0" in run_res:
                return TaskResult(
                    success=True,
                    result=run_res,
                    metadata={"tests_passed": True},
                )
            else:
                return TaskResult(
                    success=False,
                    error=f"Tests failed. Details:\n{run_res}",
                    metadata={"tests_passed": False},
                )

        except Exception as e:
            logger.error("Testing Agent failed: %s", e)
            return TaskResult(success=False, error=str(e))
