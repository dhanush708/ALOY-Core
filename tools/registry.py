import logging
from typing import Dict, List, Optional
from tools.base import ITool, ToolMetadata

logger = logging.getLogger(__name__)

class ToolRegistry:
    """Registry for managing and discovering tools."""
    
    def __init__(self):
        self._tools: Dict[str, ITool] = {}
        
    def register(self, tool: ITool) -> None:
        """Register a tool with the registry."""
        metadata = tool.metadata
        if metadata.name in self._tools:
            logger.warning(f"Overwriting registered tool: {metadata.name}")
        self._tools[metadata.name] = tool
        logger.info(f"Registered tool: {metadata.name} (category: {metadata.category})")
        
    def get(self, name: str) -> ITool:
        """Retrieve a tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Tool not found in registry: {name}")
        return self._tools[name]
        
    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools
        
    def list_all_metadata(self) -> List[ToolMetadata]:
        """List metadata for all registered tools (used for LLM schemas)."""
        return [tool.metadata for tool in self._tools.values()]
        
    def list_by_category(self, category: str) -> List[ITool]:
        """List all tools belonging to a specific category."""
        return [
            tool for tool in self._tools.values()
            if category in tool.metadata.category
        ]
