import logging
import asyncio
from typing import Dict, List, Set, Type, Optional
from .interfaces.base import ISubsystem, HealthStatus

logger = logging.getLogger(__name__)

class LifecycleManager:
    """Manages the startup and shutdown sequence of ALOY subsystems."""
    
    def __init__(self):
        # Maps subsystem instance to its dependencies (interfaces)
        self._subsystems: Dict[ISubsystem, List[Type]] = {}
        # We need the service registry to resolve dependencies
        self._registry = None
        self._boot_order: List[ISubsystem] = []
        self._is_running = False
        
    def set_registry(self, registry):
        self._registry = registry
        
    def add_subsystem(self, subsystem: ISubsystem, dependencies: List[Type] = None):
        """Add a subsystem to be managed, along with its dependencies."""
        if dependencies is None:
            dependencies = []
        self._subsystems[subsystem] = dependencies
        
    def _calculate_boot_order(self) -> List[ISubsystem]:
        """Perform topological sort to determine startup order."""
        if not self._registry:
            raise RuntimeError("Service registry not set in LifecycleManager")
            
        graph: Dict[ISubsystem, Set[ISubsystem]] = {s: set() for s in self._subsystems}
        
        # Build dependency graph
        for sub, deps in self._subsystems.items():
            for dep_interface in deps:
                if self._registry.has(dep_interface):
                    dep_instance = self._registry.get(dep_interface)
                    graph[sub].add(dep_instance)
                else:
                    logger.warning(f"Dependency {dep_interface.__name__} not found for subsystem {sub.__class__.__name__}")
                    
        # Topological sort
        in_degree = {u: 0 for u in graph}
        for u in graph:
            for v in graph[u]:
                if v in in_degree:
                    in_degree[u] += 1
                    
        queue = [u for u in graph if in_degree[u] == 0]
        order = []
        
        while queue:
            u = queue.pop(0)
            order.append(u)
            for v in graph:
                if u in graph[v]:
                    in_degree[v] -= 1
                    if in_degree[v] == 0:
                        queue.append(v)
                        
        if len(order) != len(graph):
            raise RuntimeError("Circular dependency detected in subsystems")
            
        return order
        
    async def start_all(self):
        """Start all subsystems in the correct order."""
        if self._is_running:
            return
            
        self._boot_order = self._calculate_boot_order()
        
        for subsystem in self._boot_order:
            logger.info(f"Starting subsystem: {subsystem.__class__.__name__}")
            try:
                await subsystem.start()
            except Exception as e:
                logger.error(f"Failed to start subsystem {subsystem.__class__.__name__}: {e}", exc_info=True)
                # If a subsystem fails to start, we should probably stop the ones that did
                await self.stop_all()
                raise
                
        self._is_running = True
        logger.info("All subsystems started successfully.")
        
    async def stop_all(self):
        """Stop all subsystems in reverse boot order."""
        # Stop in reverse order
        for subsystem in reversed(self._boot_order):
            logger.info(f"Stopping subsystem: {subsystem.__class__.__name__}")
            try:
                # Use wait_for to prevent a hanging subsystem from blocking shutdown
                await asyncio.wait_for(subsystem.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout stopping subsystem {subsystem.__class__.__name__}")
            except Exception as e:
                logger.error(f"Error stopping subsystem {subsystem.__class__.__name__}: {e}", exc_info=True)
                
        self._is_running = False
        self._boot_order = []
        logger.info("All subsystems stopped.")
        
    async def check_health(self) -> Dict[str, str]:
        """Check health of all subsystems."""
        health_status = {}
        for sub in self._subsystems:
            name = sub.__class__.__name__
            try:
                status = await asyncio.wait_for(sub.health_check(), timeout=2.0)
                health_status[name] = status.value
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                health_status[name] = HealthStatus.UNKNOWN.value
        return health_status
