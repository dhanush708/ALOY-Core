from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

@dataclass
class ConversationState:
    """Manages the state of a single conversation."""
    id: str
    title: Optional[str] = None
    turn_count: int = 0
    current_intent: Optional[str] = None
    emotional_tone: str = "neutral"
    topic_stack: List[str] = field(default_factory=list)
    active_memories: List[str] = field(default_factory=list)
    user_mood_estimate: Optional[str] = None
    last_model_used: Optional[str] = None
    context_token_count: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)
        
    def add_turn(self):
        """Increment turn count and update activity."""
        self.turn_count += 1
        self.update_activity()
        
    def push_topic(self, topic: str):
        """Push a topic onto the stack if not already at the top."""
        if not self.topic_stack or self.topic_stack[-1] != topic:
            self.topic_stack.append(topic)
            
    def pop_topic(self) -> Optional[str]:
        """Pop the current topic."""
        if self.topic_stack:
            return self.topic_stack.pop()
        return None
        
    def set_active_memories(self, memory_ids: List[str]):
        """Set the active memories for the current context."""
        self.active_memories = list(memory_ids)
