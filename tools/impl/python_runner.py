import asyncio
import sys
import tempfile
import os
import logging
import subprocess
from typing import Dict, Any

CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class PythonRunnerTool(BaseTool):
    """Tool for executing Python code in a subprocess with cancellation and streaming."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="python_runner",
            description="Run arbitrary Python code snippet in a separate subprocess.",
            category=["Programming"],
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code snippet to execute."
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate running the python code without executing it.",
                        "default": False
                    }
                },
                "required": ["code"]
            },
            permissions_required=["execute_command"],
            timeout_seconds=30,
            supports_streaming=True,
            supports_cancellation=True,
            supports_dry_run=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        code = params["code"]
        dry_run = params.get("dry_run", False)
        
        if dry_run:
            return f"[Dry-Run] Would execute python code:\n{code}"
            
        # Write python code to a temporary file
        # We place it in a temp file and execute it
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name
            
        is_frozen = getattr(sys, "frozen", False)
        out_temp_path = None
        env = os.environ.copy()
        if is_frozen:
            with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f2:
                out_temp_path = f2.name
            env["ALOY_STDOUT_FILE"] = out_temp_path
            
        try:
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    temp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    creationflags=CREATION_FLAGS
                )
                
                try:
                    stdout, stderr = await process.communicate()
                except asyncio.CancelledError:
                    logger.warning("Python execution cancelled, terminating subprocess.")
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except Exception:
                        process.kill()
                    raise
                    
                exit_code = process.returncode
                if is_frozen:
                    with open(out_temp_path, "r", encoding="utf-8") as f:
                        output = f.read()
                    err_output = ""
                else:
                    output = stdout.decode("utf-8", errors="replace")
                    err_output = stderr.decode("utf-8", errors="replace")
            except NotImplementedError:
                def run_sync():
                    p = subprocess.run(
                        [sys.executable, temp_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                        creationflags=CREATION_FLAGS
                    )
                    return p.returncode, p.stdout, p.stderr
                exit_code, stdout_bytes, stderr_bytes = await asyncio.to_thread(run_sync)
                if is_frozen:
                    with open(out_temp_path, "r", encoding="utf-8") as f:
                        output = f.read()
                    err_output = ""
                else:
                    output = stdout_bytes.decode("utf-8", errors="replace")
                    err_output = stderr_bytes.decode("utf-8", errors="replace")
            
            result = []
            if output:
                result.append(output)
            if err_output:
                result.append(f"Stderr:\n{err_output}")
            result.append(f"\nExit Code: {exit_code}")
            
            return "\n".join(result)
            
        finally:
            # Clean up temp file
            try:
                os.remove(temp_path)
                if out_temp_path and os.path.exists(out_temp_path):
                    os.remove(out_temp_path)
            except Exception as e:
                logger.warning(f"Failed to remove temp file: {e}")
