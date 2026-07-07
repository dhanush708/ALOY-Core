import asyncio
import logging
from typing import Dict, Any, List
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class DockerTool(BaseTool):
    """Tool for running Docker CLI commands inside the workspace."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="docker",
            description="Manage and run Docker containers (run, ps, build, exec, etc.).",
            category=["Container"],
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["ps", "run", "images", "build", "stop", "rm", "custom"],
                        "description": "Docker subcommand to execute."
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of arguments to pass to the docker command.",
                        "default": []
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate running the docker command.",
                        "default": False
                    }
                },
                "required": ["action"]
            },
            permissions_required=["execute_command"],
            timeout_seconds=60,
            supports_streaming=True,
            supports_cancellation=True,
            supports_dry_run=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        action = params["action"]
        args = params.get("args", [])
        dry_run = params.get("dry_run", False)
        
        if action == "custom":
            cmd_args = args
        else:
            cmd_args = [action] + args
            
        full_command = ["docker"] + cmd_args
        
        if dry_run:
            return f"[Dry-Run] Would execute docker command: {' '.join(full_command)}"
            
        process = await asyncio.create_subprocess_exec(
            *full_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            logger.warning(f"Docker command cancelled: {' '.join(full_command)}. Terminating subprocess...")
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                process.kill()
            raise
            
        exit_code = process.returncode
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        
        result = []
        if out:
            result.append(out)
        if err:
            result.append(f"Stderr:\n{err}")
        result.append(f"Exit Code: {exit_code}")
        
        return "\n".join(result)
