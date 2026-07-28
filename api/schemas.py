from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import datetime

class MessageRequest(BaseModel):
    content: str
    override: Optional[str] = None

class ConversationStateResponse(BaseModel):
    id: str
    title: Optional[str]
    turn_count: int
    current_intent: Optional[str]
    emotional_tone: str
    topic_stack: List[str]
    active_memories: List[str]
    last_model_used: Optional[str]
    context_token_count: int
    started_at: datetime
    last_activity: datetime

class ConversationMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    name: Optional[str]
    metadata: Dict[str, Any]
    created_at: datetime

class FeedbackRequest(BaseModel):
    feedback_type: str  # 'thumbs_up', 'thumbs_down', 'correction'
    feedback_text: Optional[str] = None

class BranchRequest(BaseModel):
    from_message_id: str

class ConversationListItemResponse(BaseModel):
    id: str
    title: Optional[str]
    last_activity: datetime

class RenameRequest(BaseModel):
    title: str

class ReportBugRequest(BaseModel):
    title: str
    description: str
    steps_to_reproduce: str
    expected_behavior: str
    actual_behavior: str
    system_information: str
