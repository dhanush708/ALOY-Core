"""Tests for ToolRegistry — registration, lookup, category filtering, and MCP interface conformance."""

import pytest
from tools.base import ToolMetadata, ITool, BaseTool
from tools.registry import ToolRegistry


class MockReadTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMetadata(
            name="mock_reader",
            description="A mock read tool.",
            category=["Filesystem", "Knowledge"],
            parameters={"type": "object", "properties": {}},
            permissions_required=["read_file"],
            timeout_seconds=5
        ))

    async def execute(self, params, context):
        return "mock read output"


class MockWriteTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMetadata(
            name="mock_writer",
            description="A mock write tool.",
            category=["Filesystem"],
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            permissions_required=["write_file"],
            timeout_seconds=10
        ))

    async def execute(self, params, context):
        return "mock write output"


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()
        self.reader = MockReadTool()
        self.writer = MockWriteTool()

    def test_register_and_get(self):
        """Registered tool can be retrieved by name."""
        self.registry.register(self.reader)
        tool = self.registry.get("mock_reader")
        assert tool is self.reader

    def test_get_raises_on_unknown_tool(self):
        """Getting an unregistered tool raises KeyError."""
        with pytest.raises(KeyError, match="mock_nonexistent"):
            self.registry.get("mock_nonexistent")

    def test_has_returns_true_for_registered_tool(self):
        self.registry.register(self.reader)
        assert self.registry.has("mock_reader") is True

    def test_has_returns_false_for_unregistered_tool(self):
        assert self.registry.has("mock_reader") is False

    def test_register_overwrites_existing_tool(self):
        """Re-registering a tool with the same name replaces it."""
        self.registry.register(self.reader)

        class MockReadToolV2(BaseTool):
            def __init__(self):
                super().__init__(ToolMetadata(
                    name="mock_reader",
                    description="Updated mock read tool.",
                    category=["Filesystem"],
                    parameters={},
                    permissions_required=["read_file"],
                    timeout_seconds=5
                ))

            async def execute(self, params, context):
                return "v2"

        reader_v2 = MockReadToolV2()
        self.registry.register(reader_v2)
        assert self.registry.get("mock_reader") is reader_v2

    def test_list_all_metadata_returns_metadata_for_all_tools(self):
        self.registry.register(self.reader)
        self.registry.register(self.writer)
        all_meta = self.registry.list_all_metadata()
        names = {m.name for m in all_meta}
        assert "mock_reader" in names
        assert "mock_writer" in names

    def test_list_by_category_filesystem(self):
        self.registry.register(self.reader)
        self.registry.register(self.writer)
        fs_tools = self.registry.list_by_category("Filesystem")
        fs_names = {t.metadata.name for t in fs_tools}
        assert "mock_reader" in fs_names
        assert "mock_writer" in fs_names

    def test_list_by_category_knowledge_only(self):
        """Only tools with category 'Knowledge' are returned."""
        self.registry.register(self.reader)
        self.registry.register(self.writer)
        knowledge_tools = self.registry.list_by_category("Knowledge")
        knowledge_names = {t.metadata.name for t in knowledge_tools}
        assert "mock_reader" in knowledge_names
        assert "mock_writer" not in knowledge_names

    def test_list_by_category_empty_when_no_matches(self):
        self.registry.register(self.writer)
        result = self.registry.list_by_category("NoSuchCategory")
        assert result == []

    def test_mcp_interface_conformance(self):
        """All registered tools implement the ITool Protocol."""
        self.registry.register(self.reader)
        self.registry.register(self.writer)
        for name in ["mock_reader", "mock_writer"]:
            tool = self.registry.get(name)
            assert isinstance(tool, ITool), f"Tool '{name}' does not conform to ITool Protocol"
            assert hasattr(tool, "metadata")
            assert hasattr(tool, "execute")
            assert callable(tool.execute)
            assert isinstance(tool.metadata, ToolMetadata)
