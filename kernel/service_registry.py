from typing import Dict, Type, TypeVar, Any

T = TypeVar('T')

class ServiceRegistry:
    """Dependency Injection container for ALOY subsystems."""
    
    def __init__(self):
        self._services: Dict[Type, Any] = {}
        
    def register(self, interface: Type[T], implementation: T) -> None:
        """Register a service implementation for an interface."""
        self._services[interface] = implementation
        
    def get(self, interface: Type[T]) -> T:
        """Get the registered implementation for an interface."""
        if interface not in self._services:
            raise KeyError(f"No service registered for interface: {interface.__name__}")
        return self._services[interface]
        
    def has(self, interface: Type[T]) -> bool:
        """Check if an interface has a registered implementation."""
        return interface in self._services
