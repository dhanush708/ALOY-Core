from typing import List, Dict, Any, Protocol
from .base import ISubsystem
from tools.base import ToolMetadata

class IToolSystem(ISubsystem, Protocol):
    """Interface for the Tool System subsystem."""
    
    def list_tools(self) -> List[ToolMetadata]:
        """List all available tools."""
        ...
        
    async def execute(self, tool_name: str, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Execute a specific tool with parameters and context."""
        ...

