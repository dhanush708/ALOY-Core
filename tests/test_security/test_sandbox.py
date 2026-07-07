import pytest
import os
from pathlib import Path
from security.sandbox import Sandbox

def test_sandbox_within_workspace(tmp_path):
    # Setup mock workspace
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    sandbox = Sandbox(str(workspace))
    
    # Inside workspace
    safe_file = workspace / "test.py"
    assert sandbox.is_within_workspace(str(safe_file))
    
    # Subdirectory
    sub_dir = workspace / "src" / "main.py"
    assert sandbox.is_within_workspace(str(sub_dir))
    
    # Exact workspace root
    assert sandbox.is_within_workspace(str(workspace))
    
def test_sandbox_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    sandbox = Sandbox(str(workspace))
    
    # Outside workspace
    outside_file = tmp_path / "other.py"
    assert not sandbox.is_within_workspace(str(outside_file))
    
    # Path traversal attempt
    traversal = workspace / ".." / "other.py"
    assert not sandbox.is_within_workspace(str(traversal))
    
    with pytest.raises(ValueError):
        sandbox.validate_path(str(traversal))
