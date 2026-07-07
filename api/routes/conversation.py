from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import uuid
from typing import List
import json
from datetime import datetime, timezone

from api.schemas import (
    MessageRequest,
    ConversationStateResponse,
    ConversationMessageResponse,
    FeedbackRequest,
    BranchRequest,
    ConversationListItemResponse,
    RenameRequest
)
from conversation.streaming import sse_stream_handler

router = APIRouter(prefix="/api/conversation", tags=["conversation"])

def get_engine(request: Request):
    return request.app.state.engine

@router.get("", response_model=List[ConversationListItemResponse])
async def list_conversations(request: Request, limit: int = 50):
    """Get all conversations ordered by last activity."""
    engine = get_engine(request)
    states = await engine.history_store.list_conversations(limit)
    return states

@router.post("")
async def create_conversation(request: Request):
    """Start a new conversation and return its state."""
    engine = get_engine(request)
    conv_id = str(uuid.uuid4())
    state = await engine.get_or_create_state(conv_id)
    return state

@router.post("/{conv_id}/message")
async def send_message(conv_id: str, payload: MessageRequest, request: Request):
    """Send a message to a conversation and get a streaming SSE response."""
    engine = get_engine(request)
    
    import asyncio
    queue = asyncio.Queue()
    task = asyncio.create_task(engine.process_message(conv_id, payload.content, event_queue=queue))
    
    return StreamingResponse(
        sse_stream_handler(task, engine, conv_id, queue=queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )

@router.get("/{conv_id}/state", response_model=ConversationStateResponse)
async def get_state(conv_id: str, request: Request):
    """Get conversation state."""
    engine = get_engine(request)
    state = await engine.history_store.get_conversation(conv_id)
    if not state:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return state

@router.get("/{conv_id}/history", response_model=List[ConversationMessageResponse])
async def get_history(conv_id: str, request: Request):
    """Get conversation history."""
    engine = get_engine(request)
    history = await engine.history_store.get_history(conv_id)
    return history

@router.post("/{conv_id}/messages/{msg_id}/feedback")
async def message_feedback(conv_id: str, msg_id: str, payload: FeedbackRequest, request: Request):
    """Log thumbs up/down or correction text feedback."""
    engine = get_engine(request)
    
    # Verify conversation exists
    state = await engine.history_store.get_conversation(conv_id)
    if not state:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    feedback_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    
    try:
        with engine.db_pool.get_write_connection() as conn:
            conn.execute("""
                INSERT INTO user_feedback (id, conversation_id, message_id, feedback_type, feedback_text, created_at, processed)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (
                feedback_id,
                conv_id,
                msg_id,
                payload.feedback_type,
                payload.feedback_text,
                created_at
            ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save feedback: {e}")
        
    return {"status": "ok", "feedback_id": feedback_id}

@router.post("/{conv_id}/messages/{msg_id}/regenerate")
async def regenerate_response(conv_id: str, msg_id: str, request: Request):
    """Regenerate assistant response for a given message ID."""
    engine = get_engine(request)
    
    # 1. Verify conversation exists
    state = await engine.history_store.get_conversation(conv_id)
    if not state:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    # 2. Get history to find user message sent before msg_id
    history = await engine.history_store.get_history(conv_id)
    
    msg_index = -1
    for i, msg in enumerate(history):
        if msg.id == msg_id:
            msg_index = i
            break
            
    if msg_index == -1:
        raise HTTPException(status_code=404, detail="Message not found")
        
    # The message to regenerate must be assistant role
    target_msg = history[msg_index]
    if target_msg.role != "assistant":
        raise HTTPException(status_code=400, detail="Can only regenerate assistant responses")
        
    # Find user message before it
    user_msg_index = msg_index - 1
    while user_msg_index >= 0 and history[user_msg_index].role != "user":
        user_msg_index -= 1
        
    if user_msg_index < 0:
        raise HTTPException(status_code=400, detail="No preceding user message found to regenerate from")
        
    user_message = history[user_msg_index]
    
    # 3. Delete the assistant message and all messages created at or after it
    target_created_at = target_msg.created_at.isoformat()
    try:
        with engine.db_pool.get_write_connection() as conn:
            conn.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ? AND created_at >= ?",
                (conv_id, target_created_at)
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear history for regeneration: {e}")
        
    # 4. Re-run the conversation pipeline using the preceding user message
    import asyncio
    queue = asyncio.Queue()
    task = asyncio.create_task(engine.process_message(conv_id, user_message.content, event_queue=queue))
    
    # Return SSE stream
    return StreamingResponse(
        sse_stream_handler(task, engine, conv_id, queue=queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@router.post("/{conv_id}/branch")
async def branch_conversation(conv_id: str, payload: BranchRequest, request: Request):
    """Branch a conversation from a specific message ID into a new session."""
    engine = get_engine(request)
    
    # 1. Verify source conversation exists
    source_state = await engine.history_store.get_conversation(conv_id)
    if not source_state:
        raise HTTPException(status_code=404, detail="Source conversation not found")
        
    # 2. Get history
    history = await engine.history_store.get_history(conv_id)
    
    msg_index = -1
    for i, msg in enumerate(history):
        if msg.id == payload.from_message_id:
            msg_index = i
            break
            
    if msg_index == -1:
        raise HTTPException(status_code=404, detail="Branch message not found")
        
    # 3. Create a new conversation session
    new_conv_id = str(uuid.uuid4())
    new_title = f"{source_state.title or 'Untitled Chat'} (Branch)"
    
    # Initialize new state
    from conversation.state import ConversationState
    new_state = ConversationState(
        id=new_conv_id,
        title=new_title,
        turn_count=msg_index + 1,
        current_intent=source_state.current_intent,
        emotional_tone=source_state.emotional_tone,
        topic_stack=source_state.topic_stack,
        active_memories=source_state.active_memories,
        last_model_used=source_state.last_model_used
    )
    
    await engine.history_store.create_conversation(new_state)
    
    # 4. Copy messages up to from_message_id
    try:
        with engine.db_pool.get_write_connection() as conn:
            for i in range(msg_index + 1):
                msg = history[i]
                new_msg_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO conversation_messages (
                        id, conversation_id, role, content, name, token_count, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_msg_id,
                    new_conv_id,
                    msg.role,
                    msg.content,
                    msg.name,
                    msg.token_count,
                    json.dumps(msg.metadata),
                    msg.created_at.isoformat()
                ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to copy messages for branching: {e}")
        
    return new_state

@router.put("/{conv_id}")
async def rename_conversation(conv_id: str, payload: RenameRequest, request: Request):
    """Rename a conversation's title."""
    engine = get_engine(request)
    try:
        with engine.db_pool.get_write_connection() as conn:
            conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (payload.title, conv_id))
        return {"status": "success", "message": "Conversation renamed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename conversation: {e}")

@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, request: Request):
    """Delete a conversation and all its messages."""
    engine = get_engine(request)
    try:
        with engine.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM conversation_messages WHERE conversation_id = ?", (conv_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        return {"status": "success", "message": "Conversation deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {e}")
