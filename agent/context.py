import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from agent.types import ExecutionContext, TaskStep, TaskStatus


class ExecutionContextBuilder:
    """Helper class to construct and serialize ExecutionContext objects."""

    @staticmethod
    def build(
        session_id: str,
        project_id: str,
        goal: str,
        workspace_path: str,
        manifest: Dict[str, Any],
        current_task: Optional[TaskStep] = None,
        conversation_context: Optional[Dict[str, Any]] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        knowledge_context: Optional[Dict[str, Any]] = None,
        reasoning_context: Optional[Dict[str, Any]] = None,
        model_context: Optional[Dict[str, Any]] = None,
        allowed_tools: Optional[List[str]] = None,
        user_permissions: Optional[List[str]] = None,
    ) -> ExecutionContext:
        resolved_path = str(Path(workspace_path).resolve().as_posix())
        
        # Default allowed tools if not specified
        if allowed_tools is None:
            allowed_tools = [
                "file_editor",
                "test_runner",
                "python_runner",
                "git",
                "web_search",
                "browser",
                "sqlite",
            ]

        # Allowed paths is strictly the workspace directory by default (plus subdirectories)
        allowed_paths = [resolved_path]

        # Manifest settings override allowed paths or tools if present
        # e.g., ignored folders in manifest.yaml
        manifest_proj = manifest.get("project", {})
        metadata = manifest_proj.get("metadata", {})
        
        # Pull extra configs if defined
        allowed_tools_manifest = metadata.get("allowed_tools")
        if isinstance(allowed_tools_manifest, list):
            allowed_tools = allowed_tools_manifest

        if user_permissions is None:
            user_permissions = ["read", "write", "test", "confirm"]

        model_ctx = model_context or {
            "planning_model": "agent_planning",
            "coding_model": "agent_coding",
            "default_model": "default",
        }

        return ExecutionContext(
            session_id=session_id,
            project_id=project_id,
            goal=goal,
            workspace_path=resolved_path,
            manifest=manifest,
            current_task=current_task,
            conversation_context=conversation_context,
            memory_context=memory_context,
            knowledge_context=knowledge_context,
            reasoning_context=reasoning_context,
            model_context=model_ctx,
            allowed_tools=allowed_tools,
            allowed_paths=allowed_paths,
            user_permissions=user_permissions,
        )

    @staticmethod
    def serialize(context: ExecutionContext) -> Dict[str, Any]:
        """Serializes the context into a JSON-compatible dictionary."""
        task_dict = None
        if context.current_task:
            task = context.current_task
            task_dict = {
                "id": task.id,
                "session_id": task.session_id,
                "assigned_agent": task.assigned_agent,
                "title": task.title,
                "description": task.description,
                "parent_task_id": task.parent_task_id,
                "priority": task.priority,
                "status": task.status.value,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "depends_on": task.depends_on,
                "result": task.result,
                "error": task.error,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
                "metadata": task.metadata,
            }

        return {
            "session_id": context.session_id,
            "project_id": context.project_id,
            "goal": context.goal,
            "workspace_path": context.workspace_path,
            "manifest": context.manifest,
            "current_task": task_dict,
            "conversation_context": context.conversation_context,
            "memory_context": context.memory_context,
            "knowledge_context": context.knowledge_context,
            "reasoning_context": context.reasoning_context,
            "model_context": context.model_context,
            "allowed_tools": context.allowed_tools,
            "allowed_paths": context.allowed_paths,
            "user_permissions": context.user_permissions,
            "extra": context.extra,
        }

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> ExecutionContext:
        """Deserializes context from a dictionary."""
        task_data = data.get("current_task")
        current_task = None
        if task_data:
            current_task = TaskStep(
                id=task_data["id"],
                session_id=task_data["session_id"],
                assigned_agent=task_data["assigned_agent"],
                title=task_data["title"],
                description=task_data["description"],
                parent_task_id=task_data.get("parent_task_id"),
                priority=task_data.get("priority", 5),
                status=TaskStatus(task_data.get("status", "pending")),
                retry_count=task_data.get("retry_count", 0),
                max_retries=task_data.get("max_retries", 3),
                depends_on=task_data.get("depends_on", []),
                result=task_data.get("result"),
                error=task_data.get("error"),
                created_at=task_data.get("created_at"),
                updated_at=task_data.get("updated_at"),
                metadata=task_data.get("metadata", {}),
            )

        return ExecutionContext(
            session_id=data["session_id"],
            project_id=data["project_id"],
            goal=data["goal"],
            workspace_path=data["workspace_path"],
            manifest=data.get("manifest", {}),
            current_task=current_task,
            conversation_context=data.get("conversation_context"),
            memory_context=data.get("memory_context"),
            knowledge_context=data.get("knowledge_context"),
            reasoning_context=data.get("reasoning_context"),
            model_context=data.get("model_context", {}),
            allowed_tools=data.get("allowed_tools", []),
            allowed_paths=data.get("allowed_paths", []),
            user_permissions=data.get("user_permissions", []),
            extra=data.get("extra", {}),
        )
