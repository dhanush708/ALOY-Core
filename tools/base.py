from dataclasses import dataclass, field
from typing import Protocol, List, Dict, Any, runtime_checkable

@dataclass
class ToolMetadata:
    name: str                        # Unique tool identifier
    description: str                 # What the tool does
    category: List[str]              # Category list for discovery (e.g., ["Filesystem"])
    parameters: Dict[str, Any]       # JSON Schema of accepted params
    permissions_required: List[str]  # e.g. ["write_file", "execute_command"]
    timeout_seconds: int = 30        # Maximum execution wall time
    estimated_cost: str = "free"     # "free" | "low" | "medium" | "high"
    supports_streaming: bool = False # Can yield partial output
    supports_cancellation: bool = False # Can be interrupted mid-run
    supports_dry_run: bool = False   # Can simulate without side-effects

@runtime_checkable
class ITool(Protocol):
    """Protocol defining the interface for all tools (local, MCP, or remote)."""
    
    @property
    def metadata(self) -> ToolMetadata:
        """Return the tool's metadata."""
        ...
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Execute the tool with parameters and context."""
        ...

class BaseTool:
    """Abstract base class for all local tool implementations."""
    
    def __init__(self, metadata: ToolMetadata):
        self._metadata = metadata
        
    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Execute the tool. Subclasses must override this."""
        raise NotImplementedError("Subclasses must implement execute")
