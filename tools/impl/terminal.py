import asyncio
import logging
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class TerminalTool(BaseTool):
    """Tool for executing terminal commands in a subprocess with cancellation and streaming."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="terminal",
            description="Execute shell commands in the workspace terminal environment.",
            category=["Terminal"],
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command line string to execute."
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate command execution without running it.",
                        "default": False
                    }
                },
                "required": ["command"]
            },
            permissions_required=["execute_command"],
            timeout_seconds=60,
            supports_streaming=True,
            supports_cancellation=True,
            supports_dry_run=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        command = params["command"]
        dry_run = params.get("dry_run", False)
        
        if dry_run:
            return f"[Dry-Run] Would execute terminal command: {command}"
            
        # Run command via shell
        # On Windows, we default to cmd.exe or PowerShell. Standard shell=True uses cmd.exe on Windows.
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            logger.warning(f"Terminal command execution cancelled. Terminating subprocess for: {command}")
            try:
                process.terminate()
                # Wait with timeout to let it terminate, then kill if necessary
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                process.kill()
            raise
            
        exit_code = process.returncode
        output = stdout.decode("utf-8", errors="replace")
        error_output = stderr.decode("utf-8", errors="replace")
        
        result = []
        if output:
            result.append(output)
        if error_output:
            result.append(f"Stderr:\n{error_output}")
        result.append(f"\nExit Code: {exit_code}")
        
        return "\n".join(result)
