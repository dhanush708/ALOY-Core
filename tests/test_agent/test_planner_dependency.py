import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from agent.agents.planner import PlannerAgent
from agent.types import TaskStep, ExecutionContext, TaskStatus

@pytest.mark.asyncio
async def test_planner_enforces_test_execution_depends_on_test_creation():
    """Verify PlannerAgent automatically ensures that test running depends on test creation."""
    agent = PlannerAgent()
    task = TaskStep(
        id="plan_1",
        session_id="session_123",
        assigned_agent="planner",
        title="Create Execution Plan",
        description="Decompose goal into tasks",
        status=TaskStatus.PENDING,
        created_at="2026-09-07T00:00:00",
        updated_at="2026-09-07T00:00:00",
    )
    context = ExecutionContext(
        session_id="session_123",
        project_id="proj_1",
        goal="implement a bubble sort algorithm in sort.py",
        workspace_path="C:/dummy/workspace",
        manifest={},
        cancellation_token=None,
    )

    # Model returns flawed plan where test_2 does not depend on test_1
    flawed_plan_json = json.dumps([
        {"id": "code_1", "assigned_agent": "coder", "title": "Implement sort.py", "description": "Write bubble sort", "depends_on": []},
        {"id": "test_1", "assigned_agent": "tester", "title": "Write Test Cases in 'sort_test.py'", "description": "Develop test cases", "depends_on": ["code_1"]},
        {"id": "test_2", "assigned_agent": "tester", "title": "Run Test Suite with pytest on 'sort_test.py'", "description": "Execute pytest suite", "depends_on": ["code_1"]},
    ])

    mock_router = MagicMock()
    mock_router.generate = AsyncMock(return_value=flawed_plan_json)

    result = await agent.execute(task, context, None, mock_router)
    assert result.success is True

    parsed_tasks = json.loads(result.result)
    test_1 = next(t for t in parsed_tasks if t["id"] == "test_1")
    test_2 = next(t for t in parsed_tasks if t["id"] == "test_2")

    # Critical assertion: test_2 MUST now depend on test_1
    assert "test_1" in test_2["depends_on"]
    assert "code_1" in test_1["depends_on"]
