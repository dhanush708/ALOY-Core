import os
import ast
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock
from agent.agents.tester import TestingAgent
from agent.types import TaskStep, ExecutionContext, TaskStatus

@pytest.mark.asyncio
async def test_tester_agent_generates_test_file():
    """Verify TestingAgent generates a valid test file when task requests test creation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a sample sort.py in the workspace
        impl_path = os.path.join(temp_dir, "sort.py")
        with open(impl_path, "w", encoding="utf-8") as f:
            f.write("""
def bubble_sort(arr):
    arr = list(arr)
    for i in range(len(arr)):
        for j in range(len(arr) - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr
""")

        agent = TestingAgent()
        task = TaskStep(
            id="test_1",
            session_id="session_123",
            assigned_agent="tester",
            title="Write Test Cases in 'sort_test.py'",
            description="Develop comprehensive test cases for bubble sort in sort_test.py.",
            status=TaskStatus.PENDING,
            created_at="2026-09-07T00:00:00",
            updated_at="2026-09-07T00:00:00",
            metadata={"file_path": "sort_test.py"}
        )
        context = ExecutionContext(
            session_id="session_123",
            project_id="proj_1",
            goal="implement bubble sort in sort.py",
            workspace_path=temp_dir,
            manifest={},
            cancellation_token=None,
        )

        mock_tool_system = MagicMock()
        async def mock_execute(tool_name, params, tool_context):
            if tool_name == "file_editor":
                with open(params["path"], "w", encoding="utf-8") as f:
                    f.write(params["content"])
                return f"Successfully wrote {params['path']}"
            return ""
        mock_tool_system.execute = AsyncMock(side_effect=mock_execute)

        mock_model_router = MagicMock()
        mock_model_router.generate = AsyncMock(return_value="""Here are the unit tests:
```python
import pytest
from sort import bubble_sort

def test_bubble_sort_empty():
    assert bubble_sort([]) == []

def test_bubble_sort_sorted():
    assert bubble_sort([1, 2, 3]) == [1, 2, 3]

def test_bubble_sort_unsorted():
    assert bubble_sort([3, 2, 1]) == [1, 2, 3]
```
""")

        result = await agent.execute(task, context, mock_tool_system, mock_model_router)
        assert result.success is True
        assert result.metadata.get("tests_generated") is True

        # Verify sort_test.py exists on disk in workspace
        target_file = os.path.join(temp_dir, "sort_test.py")
        assert os.path.exists(target_file)
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Must parse cleanly without syntax errors
        parsed = ast.parse(content)
        assert parsed is not None
        assert "def test_bubble_sort_empty():" in content
        assert "Here are the unit tests:" not in content
