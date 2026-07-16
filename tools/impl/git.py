import asyncio
import logging
import sys
import subprocess
from typing import Dict, Any, List
from tools.base import BaseTool, ToolMetadata

CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

logger = logging.getLogger(__name__)

class GitTool(BaseTool):
    """Tool for running Git commands inside the workspace."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="git",
            description="Perform Git version control operations (status, diff, log, etc.).",
            category=["Version Control"],
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "diff", "log", "add", "commit", "custom"],
                        "description": "Git subcommand or custom command."
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of arguments to pass to the git command.",
                        "default": []
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate git write operations (like commit/add).",
                        "default": False
                    }
                },
                "required": ["action"]
            },
            permissions_required=["write_file"], # Git modifications write to files
            timeout_seconds=20,
            supports_dry_run=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        action = params["action"]
        args = params.get("args", [])
        dry_run = params.get("dry_run", False)
        
        # Build command list
        if action == "custom":
            cmd_args = args
        else:
            cmd_args = [action] + args
            
        full_command = ["git"] + cmd_args
        
        # Determine if action is a write action
        is_write = action in ("add", "commit", "push", "checkout", "reset", "clean", "merge", "rebase")
        
        if is_write and dry_run:
            return f"[Dry-Run] Would run git command: {' '.join(full_command)}"
            
        process = await asyncio.create_subprocess_exec(
            *full_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=CREATION_FLAGS
        )
        
        stdout, stderr = await process.communicate()
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
