import asyncio
import logging
import time
import uuid
from typing import Dict, Any, List, Optional

from kernel.interfaces.tools import IToolSystem
from kernel.interfaces.base import HealthStatus
from kernel.types import Event
from tools.base import ToolMetadata, ITool
from tools.registry import ToolRegistry
from tools.result_formatter import ResultFormatter

logger = logging.getLogger(__name__)

# Event type constants
TOOL_STARTED = "tool.started"
TOOL_PROGRESS = "tool.progress"
TOOL_COMPLETED = "tool.completed"
TOOL_FAILED = "tool.failed"
TOOL_CANCELLED = "tool.cancelled"

class ToolSystem(IToolSystem):
    """
    Subsystem for executing tools securely within a workspace sandbox
    and under the authorization of a confirmation workflow.
    """
    
    def __init__(self, registry: ToolRegistry, sandbox, confirmation, event_bus):
        self._registry = registry
        self._sandbox = sandbox
        self._confirmation = confirmation
        self._event_bus = event_bus
        self._metrics = {
            "execution_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "cancellation_count": 0,
            "total_duration_ms": 0.0
        }
        self._active_tasks: Dict[str, asyncio.Task] = {}
        
    async def start(self) -> None:
        logger.info("ToolSystem subsystem starting...")
        
    async def stop(self) -> None:
        logger.info("ToolSystem subsystem stopping...")
        # Cancel any active tasks
        for task_id, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
        self._active_tasks.clear()
        
    async def health_check(self) -> HealthStatus:
        return HealthStatus.HEALTHY
        
    def get_metrics(self) -> Dict[str, Any]:
        return self._metrics.copy()
        
    def list_tools(self) -> List[ToolMetadata]:
        """List all available tools."""
        return self._registry.list_all_metadata()
        
    async def execute(self, tool_name: str, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Execute a tool safely, performing sandbox checks, authorization,
        timeout control, and publishing events to the Event Bus.
        """
        self._metrics["execution_count"] += 1
        start_time = time.perf_counter()
        
        session_id = context.get("session_id", "default_session")
        correlation_id = context.get("correlation_id", str(uuid.uuid4()))
        actor = context.get("actor", "agent")
        
        # 1. Look up tool
        try:
            tool = self._registry.get(tool_name)
        except KeyError as e:
            self._metrics["failure_count"] += 1
            raise ValueError(f"Tool '{tool_name}' is not registered.") from e
            
        # 2. Publish TOOL_STARTED
        params_summary = self._summarize_params(params)
        await self._event_bus.publish(Event(
            type=TOOL_STARTED,
            data={
                "tool_name": tool_name,
                "params_summary": params_summary,
                "session_id": session_id,
                "correlation_id": correlation_id
            },
            source="tool_system",
            correlation_id=correlation_id
        ))
        
        execution_id = str(uuid.uuid4())
        
        try:
            # 3. Sandbox path validation
            sanitized_params = self._validate_params_paths(params, context=context)
            
            # 4. Check permissions and request authorization
            target = self._determine_target(sanitized_params)
            perms = list(tool.metadata.permissions_required)
            
            # Dynamic specialization for read-only modes of write/execute tools
            if tool_name == "file_editor" and sanitized_params.get("action") == "read":
                perms = ["read_file"]
            elif tool_name == "git" and sanitized_params.get("action") in ("status", "diff", "log"):
                perms = ["read_file"]
            elif tool_name == "sqlite" and self._is_sqlite_read_only(sanitized_params.get("query", "")):
                perms = ["read_file"]
                
            for perm in perms:
                allowed = await self._confirmation.check_or_request_approval(
                    actor=actor,
                    action=perm,
                    target=target,
                    session_id=session_id,
                    context=context
                )
                if not allowed:
                    raise PermissionError(f"Permission denied for operation '{perm}' on target '{target}'.")
            
            # 5. Run tool with timeout limit
            timeout = tool.metadata.timeout_seconds
            
            # Run in a task so it can be cancelled if needed
            task = asyncio.create_task(tool.execute(sanitized_params, context))
            self._active_tasks[execution_id] = task
            
            try:
                raw_output = await asyncio.wait_for(task, timeout=timeout)
            except asyncio.CancelledError:
                self._metrics["cancellation_count"] += 1
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                await self._event_bus.publish(Event(
                    type=TOOL_CANCELLED,
                    data={
                        "tool_name": tool_name,
                        "reason": "Cancelled by user or runtime",
                        "duration_ms": duration_ms
                    },
                    source="tool_system",
                    correlation_id=correlation_id
                ))
                raise
            finally:
                self._active_tasks.pop(execution_id, None)
                
            # 6. Format and truncate result
            formatted_output = ResultFormatter.format(raw_output)
            
            # 7. Publish TOOL_COMPLETED
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._metrics["success_count"] += 1
            self._metrics["total_duration_ms"] += duration_ms
            
            await self._event_bus.publish(Event(
                type=TOOL_COMPLETED,
                data={
                    "tool_name": tool_name,
                    "output_size": len(formatted_output.encode("utf-8")),
                    "duration_ms": duration_ms,
                    "truncated": len(formatted_output) < len(raw_output)
                },
                source="tool_system",
                correlation_id=correlation_id
            ))
            
            return formatted_output
            
        except asyncio.TimeoutError as e:
            self._metrics["failure_count"] += 1
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            error_msg = f"Tool execution timed out after {tool.metadata.timeout_seconds} seconds."
            logger.error(f"Tool {tool_name} failed: {error_msg}")
            
            await self._event_bus.publish(Event(
                type=TOOL_FAILED,
                data={
                    "tool_name": tool_name,
                    "error_type": "TimeoutError",
                    "error_message": error_msg,
                    "duration_ms": duration_ms
                },
                source="tool_system",
                correlation_id=correlation_id
            ))
            raise TimeoutError(error_msg) from e
            
        except Exception as e:
            self._metrics["failure_count"] += 1
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(f"Tool {tool_name} failed: {error_type} - {error_msg}")
            
            await self._event_bus.publish(Event(
                type=TOOL_FAILED,
                data={
                    "tool_name": tool_name,
                    "error_type": error_type,
                    "error_message": error_msg,
                    "duration_ms": duration_ms
                },
                source="tool_system",
                correlation_id=correlation_id
            ))
            raise
            
    def _validate_params_paths(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Recursively validate path parameters using Sandbox."""
        sanitized = {}
        for k, v in params.items():
            if isinstance(v, dict):
                sanitized[k] = self._validate_params_paths(v, context=context)
            elif isinstance(v, list):
                sanitized[k] = [
                    self._validate_params_paths(item, context=context) if isinstance(item, dict) else item
                    for item in v
                ]
            elif isinstance(v, str):
                k_lower = k.lower()
                is_path_key = any(word in k_lower for word in ("path", "file", "dir", "folder", "dest", "src", "target"))
                is_content_key = any(word in k_lower for word in ("content", "text", "message", "script", "code"))
                if is_path_key and not is_content_key and v:
                    try:
                        # Path checking using workspace Sandbox
                        check_path = v
                        if not os.path.isabs(check_path) and context and context.get("workspace_path"):
                            check_path = os.path.join(context["workspace_path"], check_path)
                        sanitized[k] = self._sandbox.validate_path(check_path)
                    except ValueError as e:
                        raise PermissionError(f"Sandbox violation for path parameter '{k}': {e}") from e
                else:
                    sanitized[k] = v
            else:
                sanitized[k] = v
        return sanitized
        
    def _determine_target(self, params: Dict[str, Any]) -> str:
        """Derive the target object/file/command for confirmation logs."""
        if "path" in params:
            return str(params["path"])
        elif "filepath" in params:
            return str(params["filepath"])
        elif "command" in params:
            return str(params["command"])
        elif "query" in params:
            return str(params["query"])
        elif "script" in params:
            return str(params["script"])
        elif "code" in params:
            return str(params["code"])
        elif "url" in params:
            return str(params["url"])
        return "system"
        
    def _summarize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize parameters for public event logs (removing sensitive values)."""
        summary = {}
        for k, v in params.items():
            k_lower = k.lower()
            if any(word in k_lower for word in ("content", "script", "code", "text")):
                summary[k] = f"<content: {len(str(v))} chars>"
            else:
                summary[k] = v
        return summary

    def _is_sqlite_read_only(self, query: str) -> bool:
        q = query.strip().upper()
        write_keywords = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "REPLACE", "EXECUTE", "INTO")
        return not any(kw in q for kw in write_keywords)
