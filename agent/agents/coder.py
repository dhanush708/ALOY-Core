import logging
import re
import os
from typing import Optional

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class CodingAgent(BaseAgent):
    """
    Coding Agent writes or modifies code files.
    All filesystem changes are strictly routed through the ToolSystem.
    """

    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager

    @property
    def name(self) -> str:
        return "coder"

    @property
    def description(self) -> str:
        return "Modifies or creates files in the codebase using the Tool System."

    @property
    def preferred_model(self) -> Optional[str]:
        return "agent_coding"

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Coding Agent executing task: %s", task.id)

        tool_context = {
            "session_id": context.session_id,
            "actor": self.name,
        }

        # Retrieve mistake avoidance memory
        mistakes_summary = ""
        if self.memory_manager:
            try:
                from memory.profiles import RetrievalProfile
                memories = await self.memory_manager.retrieve_with_profile(
                    query=task.description,
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

        # 1. Ask Coding model to generate the file content
        prompt = (
            f"You are the Coding Agent. Task: {task.description}\n"
            f"Workspace path: {context.workspace_path}\n"
            f"Goal: {context.goal}\n"
            f"{mistakes_summary}\n"
            "Produce the necessary code changes. Output the complete code to write or update, "
            "and specify the filename clearly. If updating an existing file, you can output Search/Replace blocks "
            "in the format:\n"
            "<<<<<<< SEARCH\n"
            "[old code]\n"
            "=======\n"
            "[new code]\n"
            ">>>>>>> REPLACE\n"
        )

        try:
            # Generate coding plan or code itself
            code_proposal = await model_router.generate(self.preferred_model or "agent_coding", prompt)

            # 2. Extract path and content if possible, or execute file editor
            # Try to extract the target path dynamically from the LLM code proposal
            extracted_path = None
            patterns = [
                r"(?i)(?:file\s*path|filepath|file|path)\s*:\s*`?([a-zA-Z0-9_\-\.\/\\ ]+\.[a-zA-Z0-9_]+)`?",
                r"(?i)(?:create|write|update|modify|target)\s+(?:the\s+file\s+|file\s+)?`?([a-zA-Z0-9_\-\.\/\\ ]+\.[a-zA-Z0-9_]+)`?",
            ]
            for pattern in patterns:
                match = re.search(pattern, code_proposal)
                if match:
                    path_candidate = match.group(1).strip()
                    if "." in path_candidate and not path_candidate.endswith("."):
                        extracted_path = path_candidate
                        break

            if not extracted_path:
                code_blocks = re.findall(r"```[a-zA-Z]*\n(.*?)\n```", code_proposal, re.DOTALL)
                for block in code_blocks:
                    lines = block.strip().split("\n")
                    if lines:
                        first_line = lines[0].strip()
                        match = re.match(r"^(?:#|//|--)\s*([a-zA-Z0-9_\-\.\/\\ ]+)$", first_line)
                        if match:
                            path_candidate = match.group(1).strip()
                            if "." in path_candidate and not path_candidate.endswith("."):
                                extracted_path = path_candidate
                                break

            target_path = task.metadata.get("file_path") or extracted_path or "src/implementation.py"
            logger.info("Coding Agent target path resolved to: %s", target_path)
            
            # Formulate full file path
            full_path = target_path
            if not os.path.isabs(full_path):
                full_path = os.path.join(context.workspace_path, target_path)
            
            # Make sure parent dirs exist
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Write code using the tool system (either diff_engine or file_editor)
            if "<<<<<<< SEARCH" in code_proposal and ">>>>>>> REPLACE" in code_proposal:
                write_res = await tool_system.execute(
                    "diff_engine",
                    {
                        "path": full_path,
                        "patch": code_proposal,
                    },
                    tool_context,
                )
            else:
                write_res = await tool_system.execute(
                    "file_editor",
                    {
                        "path": full_path,
                        "action": "write",
                        "content": code_proposal,
                    },
                    tool_context,
                )

            return TaskResult(
                success=True,
                result=write_res,
                metadata={"modified_files": [target_path]},
            )
        except Exception as e:
            logger.error("Coding Agent failed: %s", e)
            return TaskResult(success=False, error=str(e))
