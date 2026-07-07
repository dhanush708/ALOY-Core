import json
import logging
from typing import Optional, List
from pathlib import Path

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from project.manifest import ManifestLoader
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """
    Decomposes the overall project goal into an ordered sequence of tasks,
    taking project manifest preferences and agent memory context into consideration.
    """

    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager

    @property
    def name(self) -> str:
        return "planner"

    @property
    def description(self) -> str:
        return "Decomposes high-level goals into structured task lists based on manifest preferences."

    @property
    def preferred_model(self) -> Optional[str]:
        return "agent_planning"

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Planner Agent executing for session: %s", context.session_id)

        # 1. Load manifest and merge with execution context
        workspace_path = Path(context.workspace_path)
        manifest_data = ManifestLoader.load(workspace_path)
        context.manifest = manifest_data

        # 2. Extract manifest instructions/preferences
        manifest_proj = manifest_data.get("project", {})
        project_name = manifest_proj.get("name", "Unknown")
        metadata = manifest_proj.get("metadata", {})

        framework = metadata.get("framework", "Python")
        language = metadata.get("language", "Python")
        testing_framework = metadata.get("testing_framework", "pytest")
        preferred_models = metadata.get("preferred_models", {})

        # 3. Retrieve planner-specific procedural memories
        memories_summary = ""
        if self.memory_manager:
            try:
                from memory.profiles import RetrievalProfile
                mem_hits = await self.memory_manager.retrieve_with_profile(
                    query=context.goal,
                    profile=RetrievalProfile.PLANNING,
                    limit=3,
                    extra_tags=["agent:planner", "planning"]
                )
                if mem_hits:
                    memories_summary = "\nRelevant Procedural Experiences:\n" + "\n".join(
                        f"- {m.memory.content}" for m in mem_hits
                    )
            except Exception as e:
                logger.warning("Failed to retrieve planner procedural experiences: %s", e)
        elif context.memory_context and "memories" in context.memory_context:
            mem_hits = context.memory_context.get("memories", [])
            if mem_hits:
                memories_summary = "\nRelevant Procedural Experiences:\n" + "\n".join(
                    f"- {m}" for m in mem_hits
                )

        # 4. Formulate LLM prompt to generate the plan
        system_prompt = (
            "You are the Planner Agent. Your job is to decompose the user's high-level goal "
            "into a structured plan of tasks. Each task is executed by a specialized agent."
        )

        prompt = f"""Decompose the goal into an ordered sequence of specialized tasks.

Goal: "{context.goal}"
Project: "{project_name}"
Language: {language}
Framework: {framework}
Testing Framework: {testing_framework}
{memories_summary}

Available Worker Agents:
- architect: Inspects workspace structure, defines files and module boundaries.
- coder: Modifies or creates code files.
- tester: Runs tests and checks test logs.
- documenter: Generates documentation (changelogs, readmes, APIs).

Rules for task generation:
1. Every task must have a unique 'id' (e.g. 'arch_1', 'code_1', 'test_1', 'doc_1').
2. Tasks should have 'depends_on' as a list of other task 'id's.
3. Order tasks so that dependencies are resolved sequentially.
4. Output must be a strict JSON list of objects. No additional text, markdown, or commentary.

Example output:
[
  {{"id": "arch_1", "assigned_agent": "architect", "title": "Inspect workspace", "description": "Identify relevant files", "depends_on": []}},
  {{"id": "code_1", "assigned_agent": "coder", "title": "Write codebase implementation", "description": "Add requested features", "depends_on": ["arch_1"]}},
  {{"id": "test_1", "assigned_agent": "tester", "title": "Run pytest suite", "description": "Verify code changes", "depends_on": ["code_1"]}}
]

Respond with only the JSON list:"""

        try:
            res = await model_router.generate(self.preferred_model or "agent_planning", prompt)
            
            # Clean up JSON formatting if any formatting (e.g., markdown code blocks) is returned
            res_clean = res.strip()
            if res_clean.startswith("```json"):
                res_clean = res_clean[7:]
            if res_clean.endswith("```"):
                res_clean = res_clean[:-3]
            res_clean = res_clean.strip()

            # Validate JSON
            parsed_plan = json.loads(res_clean)
            if not isinstance(parsed_plan, list):
                raise ValueError("Planner output is not a list of tasks")

            for t in parsed_plan:
                if not all(k in t for k in ("id", "assigned_agent", "title", "description", "depends_on")):
                    raise ValueError(f"Task format is missing key fields in: {t}")

            return TaskResult(
                success=True,
                result=json.dumps(parsed_plan),
                metadata={"task_count": len(parsed_plan)},
            )
        except Exception as e:
            logger.error("Planner Agent failed: %s", e)
            return TaskResult(
                success=False,
                error=f"Planner failed to generate plan: {e}",
            )
