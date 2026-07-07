from typing import Dict, List, Any


class AgentRegistry:
    """Registry to dynamically manage and look up specialized agents by name."""

    def __init__(self):
        self._agents: Dict[str, Any] = {}

    def register(self, name: str, agent: Any) -> None:
        """Register an agent under a unique name."""
        self._agents[name] = agent

    def get(self, name: str) -> Any:
        """Retrieve an agent by name. Raises KeyError if not found."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' is not registered.")
        return self._agents[name]

    def list_all(self) -> List[str]:
        """List the names of all registered agents."""
        return list(self._agents.keys())
