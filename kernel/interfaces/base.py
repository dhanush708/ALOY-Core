"""
Subsystem Interfaces for ALOY.
"""
from enum import Enum
from typing import Protocol, Dict, Any

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

class ISubsystem(Protocol):
    """Base interface for all ALOY subsystems."""
    
    async def start(self) -> None:
        """Initialize and start the subsystem."""
        ...
        
    async def stop(self) -> None:
        """Gracefully shut down the subsystem."""
        ...
        
    async def health_check(self) -> HealthStatus:
        """Check the health of the subsystem."""
        ...
        
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics for the subsystem."""
        ...
