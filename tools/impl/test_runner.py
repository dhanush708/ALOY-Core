import asyncio
import logging
import sys
import subprocess
from typing import Dict, Any, List
from tools.base import BaseTool, ToolMetadata

CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

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
        
        is_frozen = getattr(sys, "frozen", False)
        out_temp_path = None
        env = __import__("os").environ.copy()
        if is_frozen:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f2:
                out_temp_path = f2.name
            env["ALOY_STDOUT_FILE"] = out_temp_path

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                creationflags=CREATION_FLAGS
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
            if is_frozen:
                with open(out_temp_path, "r", encoding="utf-8") as f:
                    out = f.read()
                err = ""
            else:
                out = stdout.decode("utf-8", errors="replace")
                err = stderr.decode("utf-8", errors="replace")
        except NotImplementedError:
            def run_sync():
                p = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    creationflags=CREATION_FLAGS
                )
                return p.returncode, p.stdout, p.stderr
            exit_code, stdout_bytes, stderr_bytes = await asyncio.to_thread(run_sync)
            if is_frozen:
                with open(out_temp_path, "r", encoding="utf-8") as f:
                    out = f.read()
                err = ""
            else:
                out = stdout_bytes.decode("utf-8", errors="replace")
                err = stderr_bytes.decode("utf-8", errors="replace")
        finally:
            if out_temp_path:
                import os
                if os.path.exists(out_temp_path):
                    try:
                        os.remove(out_temp_path)
                    except Exception:
                        pass
        
        result = []
        if out:
            result.append(out)
        if err:
            result.append(f"Stderr:\n{err}")
        result.append(f"\nExit Code: {exit_code}")
        
        return "\n".join(result)
