import os
import logging

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class DocumentationAgent(BaseAgent):
    """
    Documentation Agent generates or updates documentation files, such as changelogs,
    Readmes, and API descriptions, strictly using the file_editor tool.
    """

    @property
    def name(self) -> str:
        return "documenter"

    @property
    def description(self) -> str:
        return "Generates and updates project documentation (changelogs, READMEs) via the Tool System."

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Documentation Agent executing task: %s", task.id)

        tool_context = {
            "session_id": context.session_id,
            "actor": self.name,
        }

        prompt = (
            f"You are the Documentation Agent. Task: {task.description}\n"
            f"Workspace: {context.workspace_path}\n"
            f"Goal: {context.goal}\n"
            "Summarize the recent modifications and generate a clear markdown changelog."
        )

        try:
            summary = await model_router.generate("agent_planning", prompt)
            
            # Write to CHANGELOG.md relative to workspace root
            changelog_path = os.path.join(context.workspace_path, "CHANGELOG.md")
            
            write_res = await tool_system.execute(
                "file_editor",
                {
                    "path": changelog_path,
                    "action": "write",
                    "content": summary,
                },
                tool_context,
            )

            return TaskResult(
                success=True,
                result=write_res,
                metadata={"changelog_created": True},
            )
        except Exception as e:
            logger.error("Documentation Agent failed: %s", e)
            return TaskResult(success=False, error=str(e))
