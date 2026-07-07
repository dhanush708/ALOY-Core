"""
Tests for ToolSystem:
  - Sandbox enforcement (path traversal blocked)
  - Write-action confirmation gate
  - Timeout enforcement
  - Output truncation via ResultFormatter
  - Event Bus publishing (STARTED, COMPLETED, FAILED)
"""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, call

from tools.base import ToolMetadata, BaseTool
from tools.registry import ToolRegistry
from tools.system import ToolSystem, TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED
from tools.result_formatter import ResultFormatter
from security.sandbox import Sandbox


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_metadata(name="test_tool", category=None, perms=None, timeout=5,
                  dry_run=False, streaming=False):
    return ToolMetadata(
        name=name,
        description="A test tool.",
        category=category or ["Testing"],
        parameters={},
        permissions_required=perms or ["read_file"],
        timeout_seconds=timeout,
        supports_dry_run=dry_run,
        supports_streaming=streaming,
    )


class EchoTool(BaseTool):
    """Returns its input params as a string."""
    def __init__(self, name="echo", delay=0.0):
        super().__init__(make_metadata(name=name))
        self._delay = delay

    async def execute(self, params, context):
        if self._delay:
            await asyncio.sleep(self._delay)
        return f"echo: {params}"


class FailTool(BaseTool):
    """Always raises RuntimeError."""
    def __init__(self):
        super().__init__(make_metadata(name="fail_tool"))

    async def execute(self, params, context):
        raise RuntimeError("Intentional failure")


def make_tool_system(tool: BaseTool, *, workspace: str = None,
                     confirmation_result: bool = True):
    """Create a ToolSystem wired with a mock sandbox, confirmation, and event bus."""
    if workspace is None:
        import tempfile, os
        workspace = tempfile.gettempdir()

    sandbox = Sandbox(workspace)

    confirmation = AsyncMock()
    confirmation.check_or_request_approval = AsyncMock(return_value=confirmation_result)

    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()

    registry = ToolRegistry()
    registry.register(tool)

    system = ToolSystem(registry, sandbox, confirmation, event_bus)
    return system, event_bus, confirmation


def default_context():
    return {
        "session_id": "sess-test",
        "actor": "agent",
        "correlation_id": "corr-001",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_execution_publishes_started_and_completed():
    """A successful tool call publishes TOOL_STARTED then TOOL_COMPLETED."""
    tool = EchoTool()
    system, event_bus, _ = make_tool_system(tool)

    result = await system.execute("echo", {}, default_context())

    assert "echo:" in result

    publish_calls = event_bus.publish.call_args_list
    event_types = [c.args[0].type for c in publish_calls]
    assert TOOL_STARTED in event_types
    assert TOOL_COMPLETED in event_types
    assert TOOL_FAILED not in event_types


@pytest.mark.asyncio
async def test_failed_tool_publishes_tool_failed_event():
    """A tool that raises an exception should publish TOOL_FAILED."""
    tool = FailTool()
    system, event_bus, _ = make_tool_system(tool)

    with pytest.raises(RuntimeError, match="Intentional failure"):
        await system.execute("fail_tool", {}, default_context())

    publish_calls = event_bus.publish.call_args_list
    event_types = [c.args[0].type for c in publish_calls]
    assert TOOL_FAILED in event_types


@pytest.mark.asyncio
async def test_timeout_raises_and_publishes_failed():
    """A tool that exceeds its timeout should raise TimeoutError and publish TOOL_FAILED."""
    class SlowTool(BaseTool):
        def __init__(self):
            super().__init__(make_metadata(name="slow_tool", timeout=1))
        async def execute(self, params, context):
            await asyncio.sleep(5)
            return "done"

    tool = SlowTool()
    system, event_bus, _ = make_tool_system(tool)

    with pytest.raises(TimeoutError):
        await system.execute("slow_tool", {}, default_context())

    event_types = [c.args[0].type for c in event_bus.publish.call_args_list]
    assert TOOL_FAILED in event_types


@pytest.mark.asyncio
async def test_path_traversal_raises_permission_error():
    """Params containing paths outside workspace root should be blocked immediately."""
    import tempfile, os
    workspace = tempfile.gettempdir()
    tool = EchoTool()
    system, event_bus, _ = make_tool_system(tool, workspace=workspace)

    # Use a path guaranteed to be outside the workspace temp dir
    outside_path = "C:\\Windows\\System32\\evil.exe"

    with pytest.raises(PermissionError, match="Sandbox violation"):
        await system.execute("echo", {"path": outside_path}, default_context())


@pytest.mark.asyncio
async def test_confirmation_denial_raises_permission_error():
    """When confirmation workflow denies permission, ToolSystem raises PermissionError."""
    class WriteFileTool(BaseTool):
        def __init__(self):
            super().__init__(make_metadata(name="write_tool", perms=["write_file"]))
        async def execute(self, params, context):
            return "written"

    tool = WriteFileTool()
    system, event_bus, confirmation = make_tool_system(tool, confirmation_result=False)

    with pytest.raises(PermissionError, match="Permission denied"):
        await system.execute("write_tool", {}, default_context())


@pytest.mark.asyncio
async def test_unknown_tool_raises_value_error():
    """Attempting to execute a tool that is not registered raises ValueError."""
    tool = EchoTool()
    system, event_bus, _ = make_tool_system(tool)

    with pytest.raises(ValueError, match="not registered"):
        await system.execute("nonexistent_tool", {}, default_context())


@pytest.mark.asyncio
async def test_metrics_updated_on_success():
    """Metrics counters increment correctly after a successful execution."""
    tool = EchoTool()
    system, _, _ = make_tool_system(tool)

    await system.execute("echo", {}, default_context())

    m = system.get_metrics()
    assert m["execution_count"] == 1
    assert m["success_count"] == 1
    assert m["failure_count"] == 0


@pytest.mark.asyncio
async def test_metrics_updated_on_failure():
    """Metrics counters increment correctly after a failed execution."""
    tool = FailTool()
    system, _, _ = make_tool_system(tool)

    with pytest.raises(RuntimeError):
        await system.execute("fail_tool", {}, default_context())

    m = system.get_metrics()
    assert m["execution_count"] == 1
    assert m["failure_count"] == 1
    assert m["success_count"] == 0


def test_list_tools_returns_all_metadata():
    """list_tools() returns ToolMetadata for every registered tool."""
    registry = ToolRegistry()
    t1 = EchoTool("t1")
    t2 = EchoTool("t2")
    registry.register(t1)
    registry.register(t2)

    sandbox = Sandbox(".")
    system = ToolSystem(registry, sandbox, AsyncMock(), AsyncMock())

    tools = system.list_tools()
    names = {m.name for m in tools}
    assert "t1" in names
    assert "t2" in names


class TestResultFormatter:
    def test_short_output_not_truncated(self):
        output = "Hello World"
        result = ResultFormatter.format(output, max_bytes=1024)
        assert result == output

    def test_long_output_truncated_with_warning(self):
        big_text = "x" * 200_000
        result = ResultFormatter.format(big_text, max_bytes=100 * 1024)
        assert "[output truncated:" in result

    def test_empty_output_returns_empty(self):
        assert ResultFormatter.format("") == ""
