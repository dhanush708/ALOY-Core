import asyncio
import logging
import sys
from typing import Dict, Any, List
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class RunnerTool(BaseTool):
    """Tool for running test suites (pytest) in the workspace."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="test_runner",
            description="Run automated unit/integration tests using pytest.",
            category=["Testing"],
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Specific test file or directory path relative to workspace root.",
                        "default": ""
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional command-line options for pytest (e.g., ['-v', '-k', 'test_name']).",
                        "default": []
                    }
                }
            },
            permissions_required=["execute_command"],
            timeout_seconds=45,
            supports_streaming=True,
            supports_cancellation=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        path = params.get("path", "")
        options = params.get("options", [])
        
        # Build command: python -m pytest [path] [options...]
        command = [sys.executable, "-m", "pytest"]
        if path:
            command.append(path)
        command.extend(options)
        
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await process.communicate()
            except asyncio.CancelledError:
                logger.warning("Test runner execution cancelled. Terminating subprocess...")
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except Exception:
                    process.kill()
                raise
                
            exit_code = process.returncode
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
        except NotImplementedError:
            import subprocess
            def run_sync():
                p = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                return p.returncode, p.stdout, p.stderr
            exit_code, stdout_bytes, stderr_bytes = await asyncio.to_thread(run_sync)
            out = stdout_bytes.decode("utf-8", errors="replace")
            err = stderr_bytes.decode("utf-8", errors="replace")
        
        result = []
        if out:
            result.append(out)
        if err:
            result.append(f"Stderr:\n{err}")
        result.append(f"\nExit Code: {exit_code}")
        
        return "\n".join(result)
