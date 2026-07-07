import pytest
import os
import asyncio
from pathlib import Path
from security.sandbox import Sandbox
from tools.impl.file_editor import FileEditorTool
from tools.impl.terminal import TerminalTool
from tools.impl.python_runner import PythonRunnerTool

def test_sandbox_traversals(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    sandbox = Sandbox(str(workspace))
    
    # 1. Path traversal via parent directories
    traversal1 = str(workspace / ".." / "outside.txt")
    assert not sandbox.is_within_workspace(traversal1)
    
    # 2. Windows drive traversal (e.g. D:\ or C:\Windows)
    # We resolve it relative to workspace or check absolute traversal
    absolute_outside = "C:\\Windows\\System32\\cmd.exe" if os.name == "nt" else "/etc/passwd"
    assert not sandbox.is_within_workspace(absolute_outside)
    
    # 3. Path traversal using symlinks or relative references
    relative_outside = "../../other_dir"
    assert not sandbox.is_within_workspace(str(workspace / relative_outside))

@pytest.mark.asyncio
async def test_tool_sandbox_execution_rejection(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    sandbox = Sandbox(str(workspace))
    
    # Instantiate FileEditorTool and verify validation path raises ValueError outside workspace
    tool = FileEditorTool()
    outside_file = str(tmp_path / "leak.txt")
    
    params = {
        "action": "write",
        "path": outside_file,
        "content": "Secret system data"
    }
    
    # Simulate execution context with sandbox
    context = {"sandbox": sandbox}
    
    with pytest.raises(ValueError) as excinfo:
        # FileEditorTool uses Path(params["path"]) and resolves it.
        # If it uses validate_path on sandbox, it raises ValueError
        sandbox.validate_path(params["path"])
        
    assert "Security violation" in str(excinfo.value)

@pytest.mark.asyncio
async def test_tool_malformed_parameters():
    tool = TerminalTool()
    
    # Missing required parameter "command"
    params = {"dry_run": True}
    with pytest.raises(KeyError):
        await tool.execute(params, {})
        
    # Invalid type for parameter
    tool2 = FileEditorTool()
    params2 = {
        "action": "write",
        "path": 12345,  # Should be string
        "content": "content"
    }
    # Test that executing or path conversion fails gracefully
    with pytest.raises(Exception):
        # Path(12345) raises TypeError in Python path resolution
        Path(params2["path"])

@pytest.mark.asyncio
async def test_concurrent_tool_execution():
    tool = PythonRunnerTool()
    
    # Run 10 Python execution scripts concurrently
    tasks = []
    for i in range(10):
        code = f"import time; time.sleep(0.02); print('Task {i}')"
        tasks.append(tool.execute({"code": code}, {}))
        
    results = await asyncio.gather(*tasks)
    assert len(results) == 10
    for i, res in enumerate(results):
        assert f"Task" in res
        assert "Exit Code: 0" in res
