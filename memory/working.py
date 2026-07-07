import logging
from typing import Dict, List, Optional
from .types import Memory

logger = logging.getLogger(__name__)

class WorkingMemory:
    """In-process buffer for active conversation context."""
    
    def __init__(self):
        # Maps conversation_id -> list of active memories
        self.buffers: Dict[str, List[Memory]] = {}
        
    def add(self, conversation_id: str, memory: Memory) -> None:
        """Add a memory to the active conversation buffer."""
        if conversation_id not in self.buffers:
            self.buffers[conversation_id] = []
            
        # Don't add if already present in buffer
        if any(m.id == memory.id for m in self.buffers[conversation_id]):
            return
            
        self.buffers[conversation_id].append(memory)
        
    def remove(self, conversation_id: str, memory_id: str) -> None:
        """Remove a memory from the active buffer."""
        if conversation_id in self.buffers:
            self.buffers[conversation_id] = [
                m for m in self.buffers[conversation_id] if m.id != memory_id
            ]
            
    def get_all(self, conversation_id: str) -> List[Memory]:
        """Get all memories in the current buffer."""
        return self.buffers.get(conversation_id, [])
        
    def clear(self, conversation_id: str) -> None:
        """Clear the buffer for a conversation (e.g. when ended)."""
        if conversation_id in self.buffers:
            del self.buffers[conversation_id]
