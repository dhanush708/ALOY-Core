from typing import Dict, Any, Protocol
from .base import ISubsystem

class ISecuritySystem(ISubsystem, Protocol):
    """Interface for the Security System subsystem."""
    
    async def check_permission(self, action: str, target: str) -> bool:
        """Check if an action on a target is permitted."""
        ...
        
    async def request_approval(self, action: str, details: Dict[str, Any]) -> bool:
        """Request user approval for a dangerous action."""
        ...
        
    async def audit(self, entry: Any) -> None:
        """Log an action to the secure audit trail."""
        ...
