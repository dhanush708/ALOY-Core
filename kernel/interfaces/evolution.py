from typing import Any, Protocol
from .base import ISubsystem

class IEvolutionEngine(ISubsystem, Protocol):
    """Interface for the Self-Evolution Engine subsystem."""
    
    async def propose_evolution(self, component: str, new_logic: str) -> Any:
        """Propose an evolutionary change to the system."""
        ...
