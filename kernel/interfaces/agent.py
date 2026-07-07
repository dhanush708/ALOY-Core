from typing import Any, Protocol
from .base import ISubsystem

class IAgentEngine(ISubsystem, Protocol):
    """Interface for the Coding Agent Engine subsystem."""
    
    async def execute_objective(self, objective: str, project_id: str) -> Any:
        """Execute a complex coding objective autonomously."""
        ...
