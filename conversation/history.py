import logging
import json
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from .state import ConversationState

logger = logging.getLogger(__name__)

@dataclass
class ConversationMessage:
    id: str
    conversation_id: str
    role: str
    content: str
    name: Optional[str] = None
    token_count: Optional[int] = None
    metadata: Dict[str, Any] = None
    created_at: datetime = None

class ConversationStore:
    """Manages conversations and messages in the database."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
        
    async def create_conversation(self, state: Optional[ConversationState] = None) -> ConversationState:
        if not state:
            state = ConversationState(id=str(uuid.uuid4()))
            
        with self.db_pool.get_write_connection() as conn:
            conn.execute("""
                INSERT INTO conversations (
                    id, title, turn_count, current_intent, emotional_tone,
                    topic_stack, active_memories, user_mood_estimate, last_model_used,
                    context_token_count, started_at, last_activity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state.id, state.title, state.turn_count, state.current_intent, state.emotional_tone,
                json.dumps(state.topic_stack), json.dumps(state.active_memories), 
                state.user_mood_estimate, state.last_model_used,
                state.context_token_count, state.started_at.isoformat(), state.last_activity.isoformat()
            ))
            
        return state

    async def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
                
            return ConversationState(
                id=row["id"],
                title=row["title"],
                turn_count=row["turn_count"],
                current_intent=row["current_intent"],
                emotional_tone=row["emotional_tone"],
                topic_stack=json.loads(row["topic_stack"]) if row["topic_stack"] else [],
                active_memories=json.loads(row["active_memories"]) if row["active_memories"] else [],
                user_mood_estimate=row["user_mood_estimate"],
                last_model_used=row["last_model_used"],
                context_token_count=row["context_token_count"],
                started_at=datetime.fromisoformat(row["started_at"]),
                last_activity=datetime.fromisoformat(row["last_activity"])
            )

    async def update_conversation(self, state: ConversationState) -> None:
        with self.db_pool.get_write_connection() as conn:
            conn.execute("""
                UPDATE conversations SET
                    title = ?, turn_count = ?, current_intent = ?, emotional_tone = ?,
                    topic_stack = ?, active_memories = ?, user_mood_estimate = ?,
                    last_model_used = ?, context_token_count = ?, last_activity = ?
                WHERE id = ?
            """, (
                state.title, state.turn_count, state.current_intent, state.emotional_tone,
                json.dumps(state.topic_stack), json.dumps(state.active_memories),
                state.user_mood_estimate, state.last_model_used,
                state.context_token_count, state.last_activity.isoformat(),
                state.id
            ))

    async def add_message(
        self, 
        conversation_id: str, 
        role: str, 
        content: str, 
        name: Optional[str] = None,
        token_count: Optional[int] = None,
        metadata: Optional[Dict] = None,
        created_at: Optional[datetime] = None
    ) -> ConversationMessage:
        msg_id = str(uuid.uuid4())
        msg_created_at = created_at or datetime.now(timezone.utc)
        
        msg = ConversationMessage(
            id=msg_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            name=name,
            token_count=token_count,
            metadata=metadata or {},
            created_at=msg_created_at
        )
        
        with self.db_pool.get_write_connection() as conn:
            conn.execute("""
                INSERT INTO conversation_messages (
                    id, conversation_id, role, content, name, token_count, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg.id, msg.conversation_id, msg.role, msg.content, msg.name, 
                msg.token_count, json.dumps(msg.metadata), msg.created_at.isoformat()
            ))
            
        return msg

    async def get_history(self, conversation_id: str, limit: int = 50) -> List[ConversationMessage]:
        with self.db_pool.get_read_connection() as conn:
            # Get latest 'limit' messages, ordered by created_at DESC to limit, then reverse in python
            cursor = conn.execute("""
                SELECT * FROM conversation_messages 
                WHERE conversation_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (conversation_id, limit))
            
            rows = cursor.fetchall()
            
        messages = []
        for row in reversed(rows):
            messages.append(ConversationMessage(
                id=row["id"],
                conversation_id=row["conversation_id"],
                role=row["role"],
                content=row["content"],
                name=row["name"],
                token_count=row["token_count"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=datetime.fromisoformat(row["created_at"])
            ))
            
        return messages

    async def list_conversations(self, limit: int = 50) -> List[ConversationState]:
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM conversations 
                ORDER BY last_activity DESC 
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            
        states = []
        for row in rows:
            states.append(ConversationState(
                id=row["id"],
                title=row["title"],
                turn_count=row["turn_count"],
                current_intent=row["current_intent"],
                emotional_tone=row["emotional_tone"],
                topic_stack=json.loads(row["topic_stack"]) if row["topic_stack"] else [],
                active_memories=json.loads(row["active_memories"]) if row["active_memories"] else [],
                user_mood_estimate=row["user_mood_estimate"],
                last_model_used=row["last_model_used"],
                context_token_count=row["context_token_count"],
                started_at=datetime.fromisoformat(row["started_at"]),
                last_activity=datetime.fromisoformat(row["last_activity"])
            ))
            
        return states

