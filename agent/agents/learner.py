import logging
from typing import Dict, Any

from agent.types import TaskStep, ExecutionContext, TaskResult
from agent.agents.base import BaseAgent
from models.router import ModelRouter
from kernel.types import Event, LEARNING_TASK_QUEUED

logger = logging.getLogger(__name__)


class LearningAgent(BaseAgent):
    """
    Learning Agent reviews execution journals, identifies mistakes/lessons,
    and publishes structured events to the Event Bus for the Learning Engine to ingest.
    """

    def __init__(self, event_bus):
        self.event_bus = event_bus

    @property
    def name(self) -> str:
        return "learner"

    @property
    def description(self) -> str:
        return "Extracts lessons/mistakes from coding sessions and publishes learning tasks."

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router: ModelRouter,
    ) -> TaskResult:
        logger.info("Learning Agent executing task: %s", task.id)

        prompt = (
            f"Review the goal '{context.goal}' and output lessons learned, "
            "successful patterns, bugs resolved, and strategies identified in a clear dictionary structure."
        )

        try:
            analysis = await model_router.generate("agent_planning", prompt)

            # Publish learning event to Event Bus (to be ingested by the Learning Engine)
            # The event data must match what the Learning Engine reflection pipeline expects
            await self.event_bus.publish(
                Event(
                    type=LEARNING_TASK_QUEUED,
                    data={
                        "session_id": context.session_id,
                        "project_id": context.project_id,
                        "workspace_path": context.workspace_path,
                        "lessons": analysis,
                        "timestamp": task.created_at,
                    },
                    source="learning_agent",
                )
            )

            return TaskResult(
                success=True,
                result=f"Published learning task. Analysis summary:\n{analysis}",
                metadata={"learning_event_published": True},
            )
        except Exception as e:
            logger.error("Learning Agent failed: %s", e)
            return TaskResult(success=False, error=str(e))
