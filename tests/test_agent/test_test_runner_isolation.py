import os
import sys
import tempfile
import pytest
from tools.impl.test_runner import RunnerTool

@pytest.mark.asyncio
async def test_test_runner_workspace_isolation():
    """Verify test_runner executes in the workspace directory and does NOT collect ALOY repo tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a simple test file inside temp_dir
        test_file = os.path.join(temp_dir, "test_sample.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("""
def test_addition():
    assert 1 + 1 == 2
""")
        
        tool = RunnerTool()
        result = await tool.execute(
            {"path": "test_sample.py", "cwd": temp_dir, "options": ["-v"]},
            {"session_id": "test_session", "workspace_path": temp_dir}
        )
        
        assert "Exit Code: 0" in result
        assert "test_addition PASSED" in result
        # Crucial: Must execute inside temp_dir and NOT collect ALOY codebase tests
        assert "ALOY" not in result or "rootdir:" in result
        assert "test_meta_routing" not in result

@pytest.mark.asyncio
async def test_test_runner_file_not_found():
    """Verify test_runner returns Exit Code 4 when target test file does not exist."""
    with tempfile.TemporaryDirectory() as temp_dir:
        tool = RunnerTool()
        result = await tool.execute(
            {"path": "non_existent_test.py", "cwd": temp_dir},
            {"workspace_path": temp_dir}
        )
        assert "Exit Code: 4" in result
        assert "Test file or directory not found" in result

@pytest.mark.asyncio
async def test_test_runner_empty_workspace_no_tests():
    """Verify test_runner returns Exit Code 5 when workspace has no tests matching test_*.py or *_test.py."""
    with tempfile.TemporaryDirectory() as temp_dir:
        tool = RunnerTool()
        result = await tool.execute(
            {"path": "", "cwd": temp_dir},
            {"workspace_path": temp_dir}
        )
        assert "Exit Code: 5" in result
        assert "No test files found in workspace" in result

@pytest.mark.asyncio
async def test_test_runner_assertion_failure():
    """Verify test_runner genuinely returns Exit Code 1 on test assertion failure."""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file = os.path.join(temp_dir, "test_fail.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("""
def test_failure():
    assert 2 + 2 == 5
""")
        tool = RunnerTool()
        result = await tool.execute(
            {"path": "test_fail.py", "cwd": temp_dir},
            {"workspace_path": temp_dir}
        )
        assert "Exit Code: 1" in result
        assert "FAILED" in result
        assert "assert 2 + 2 == 5" in result
