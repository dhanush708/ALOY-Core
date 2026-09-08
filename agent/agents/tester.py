import os
import re
import logging
from typing import Optional

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from agent.agents.coder import extract_clean_code
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
        logger.info("Testing Agent executing task: %s", task.id)

        tool_context = {
            "session_id": context.session_id,
            "actor": self.name,
            "workspace_path": context.workspace_path,
        }

        task_text = f"{task.title} {task.description}".lower()
        
        # Determine if this task explicitly requests test creation/generation
        is_generation = (
            any(kw in task_text for kw in (
                "write test", "generate test", "create test", "develop test",
                "add test", "implement test", "author test", "test creation", "test generation"
            ))
            or task.metadata.get("action") in ("generate", "write", "create")
        )
        # If the task is purely test execution (e.g. "Run Test Suite"), do not regenerate
        if ("run test" in task_text or "execute test" in task_text or "run pytest" in task_text) and not any(
            kw in task_text for kw in ("write test", "generate test", "create test", "develop test")
        ):
            is_generation = False

        if is_generation:
            return await self._generate_tests(task, context, tool_system, model_router, tool_context)
        else:
            return await self._run_tests(task, context, tool_system, tool_context)

    async def _generate_tests(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
        tool_context: dict,
    ) -> TaskResult:
        """Generates pytest test cases and writes them to workspace using file_editor."""
        try:
            # 1. Inspect workspace for existing source files to provide context
            source_context = ""
            workspace_files = []
            if os.path.isdir(context.workspace_path):
                for root, dirs, files in os.walk(context.workspace_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv")]
                    for f in files:
                        if f.endswith(".py") and not (f.startswith("test_") or f.endswith("_test.py")):
                            f_path = os.path.join(root, f)
                            workspace_files.append(f_path)

            for wf in workspace_files[:3]:
                try:
                    rel_name = os.path.relpath(wf, context.workspace_path)
                    with open(wf, "r", encoding="utf-8", errors="replace") as sf:
                        content = sf.read()
                    source_context += f"\nFile `{rel_name}`:\n```python\n{content[:2000]}\n```\n"
                except Exception as e:
                    logger.warning("Could not read workspace file for test context: %s", e)

            # 2. Determine target test file path
            target_path = task.metadata.get("file_path") or task.metadata.get("test_path")
            if not target_path:
                match = re.search(r"['\"`]([a-zA-Z0-9_\-\.\/\\ ]+\.py)['\"`]", f"{task.title} {task.description}")
                if match:
                    target_path = match.group(1).strip()
                elif workspace_files:
                    base_name = os.path.splitext(os.path.basename(workspace_files[0]))[0]
                    target_path = f"test_{base_name}.py"
                else:
                    target_path = "test_solution.py"

            full_path = target_path if os.path.isabs(target_path) else os.path.join(context.workspace_path, target_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # 3. Prompt model to generate pytest tests
            prompt = (
                f"You are the Testing Agent. Task: {task.description}\n"
                f"Target file: {target_path}\n"
                f"Workspace path: {context.workspace_path}\n"
                f"Goal: {context.goal}\n"
                f"{source_context}\n"
                "Write comprehensive, robust automated unit tests using pytest. "
                "Import the functions or classes directly from the source module. "
                "Cover nominal cases, boundary conditions, edge cases, and error handling. "
                "Output ONLY the complete Python test code within a ```python code block."
            )

            raw_code = await model_router.generate(self.preferred_model or "agent_coding", prompt)
            clean_code = extract_clean_code(raw_code, target_path)

            # 4. Write test file using tool system
            write_res = await tool_system.execute(
                "file_editor",
                {
                    "path": full_path,
                    "action": "write",
                    "content": clean_code,
                },
                tool_context,
            )

            logger.info("Testing Agent successfully wrote test file: %s", full_path)
            return TaskResult(
                success=True,
                result=f"Generated and wrote test file {target_path}:\n{write_res}",
                metadata={"test_file": target_path, "tests_generated": True},
            )
        except Exception as e:
            logger.error("Testing Agent test generation failed: %s", e)
            return TaskResult(success=False, error=f"Test generation failed: {e}")

    async def _run_tests(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        tool_context: dict,
    ) -> TaskResult:
        """Executes test suite via test_runner tool."""
        try:
            test_path = task.metadata.get("test_path") or ""
            if not test_path:
                match = re.search(r"['\"`]([a-zA-Z0-9_\-\.\/\\ ]+\.py)['\"`]", f"{task.title} {task.description}")
                if match:
                    candidate = match.group(1).strip()
                    cand_base = os.path.basename(candidate)
                    if cand_base.startswith("test_") or cand_base.endswith("_test.py"):
                        candidate_full = candidate if os.path.isabs(candidate) else os.path.join(context.workspace_path, candidate)
                        if os.path.exists(candidate_full):
                            test_path = candidate

            # If no explicit test file matched, search workspace for existing test files
            if not test_path and os.path.isdir(context.workspace_path):
                for root, dirs, files in os.walk(context.workspace_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv")]
                    for f in sorted(files):
                        if f.startswith("test_") or f.endswith("_test.py"):
                            test_path = os.path.relpath(os.path.join(root, f), context.workspace_path)
                            break
                    if test_path:
                        break

            full_test_path = test_path
            if test_path and not os.path.isabs(test_path):
                full_test_path = os.path.join(context.workspace_path, test_path)

            options = task.metadata.get("options") or ["-v"]

            run_res = await tool_system.execute(
                "test_runner",
                {
                    "path": full_test_path,
                    "cwd": context.workspace_path,
                    "options": options,
                },
                tool_context,
            )

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
            logger.error("Testing Agent test execution failed: %s", e)
            return TaskResult(success=False, error=str(e))
