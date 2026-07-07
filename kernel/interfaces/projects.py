from typing import List, Dict, Any, Protocol
from .base import ISubsystem

class IProjectManager(ISubsystem, Protocol):
    """Interface for the Project Management subsystem."""
    
    async def create_project(self, name: str, description: str) -> str:
        """Create a new project workspace."""
        ...
        
    async def list_projects(self) -> List[Dict[str, Any]]:
        """List all projects."""
        ...
