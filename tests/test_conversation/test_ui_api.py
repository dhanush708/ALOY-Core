import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from api.server import app
from conversation.state import ConversationState
from conversation.history import ConversationMessage

@pytest.fixture
def mock_app_state():
    # Setup mocks
    app.state.engine = MagicMock()
    app.state.engine.get_or_create_state = AsyncMock()
    app.state.engine.process_message = AsyncMock()
    app.state.engine.history_store = MagicMock()
    app.state.engine.history_store.get_conversation = AsyncMock()
    app.state.engine.history_store.get_history = AsyncMock()
    app.state.engine.history_store.create_conversation = AsyncMock()
    app.state.engine.history_store.list_conversations = AsyncMock()
    
    # DB mocks
    app.state.engine.db_pool = MagicMock()
    conn_mock = MagicMock()
    app.state.engine.db_pool.get_write_connection.return_value.__enter__.return_value = conn_mock
    
    return app.state.engine

def test_list_conversations(mock_app_state):
    # Setup return list
    mock_app_state.history_store.list_conversations.return_value = [
        ConversationState(id="c1", title="Chat 1", started_at=datetime.now(timezone.utc), last_activity=datetime.now(timezone.utc)),
        ConversationState(id="c2", title="Chat 2", started_at=datetime.now(timezone.utc), last_activity=datetime.now(timezone.utc))
    ]
    
    client = TestClient(app)
    response = client.get("/api/conversation")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["id"] == "c1"
    assert data[0]["title"] == "Chat 1"

def test_message_feedback_logging(mock_app_state):
    # Mock conversation check
    mock_app_state.history_store.get_conversation.return_value = ConversationState(id="c1")
    
    client = TestClient(app)
    response = client.post("/api/conversation/c1/messages/m1/feedback", json={
        "feedback_type": "thumbs_up",
        "feedback_text": "Good explanation!"
    })
    
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "feedback_id" in response.json()
    
    # Assert DB insert called
    conn = mock_app_state.db_pool.get_write_connection.return_value.__enter__.return_value
    assert conn.execute.called

@pytest.mark.asyncio
async def test_conversation_branching(mock_app_state):
    # Mock source conversation and history
    mock_app_state.history_store.get_conversation.return_value = ConversationState(id="c1", title="Source Chat")
    
    mock_app_state.history_store.get_history.return_value = [
        ConversationMessage(id="m1", conversation_id="c1", role="user", content="hello", created_at=datetime.now(timezone.utc), metadata={}),
        ConversationMessage(id="m2", conversation_id="c1", role="assistant", content="hi", created_at=datetime.now(timezone.utc), metadata={}),
        ConversationMessage(id="m3", conversation_id="c1", role="user", content="branch off here", created_at=datetime.now(timezone.utc), metadata={})
    ]
    
    client = TestClient(app)
    response = client.post("/api/conversation/c1/branch", json={
        "from_message_id": "m2"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["title"] == "Source Chat (Branch)"
    
    # Assert copy of messages called
    conn = mock_app_state.db_pool.get_write_connection.return_value.__enter__.return_value
    # It should copy m1 and m2 (2 messages)
    assert conn.execute.call_count >= 2

@patch("api.routes.conversation.sse_stream_handler")
def test_response_regeneration(mock_sse_handler, mock_app_state):
    # Setup mock handler
    async def mock_generator():
        yield "data: {}\n\n"
    mock_sse_handler.return_value = mock_generator()
    
    # Mock source conversation and history
    mock_app_state.history_store.get_conversation.return_value = ConversationState(id="c1")
    
    mock_app_state.history_store.get_history.return_value = [
        ConversationMessage(id="m1", conversation_id="c1", role="user", content="what is code?", created_at=datetime.now(timezone.utc), metadata={}),
        ConversationMessage(id="m2", conversation_id="c1", role="assistant", content="code is logic", created_at=datetime.now(timezone.utc), metadata={})
    ]
    
    # Mock context return
    mock_context = MagicMock()
    mock_context.intent = "simple_chat"
    mock_context.model = "qwen3:8b"
    mock_context.response_stream = mock_generator()
    mock_app_state.process_message.return_value = mock_context
    
    client = TestClient(app)
    response = client.post("/api/conversation/c1/messages/m2/regenerate")
    
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    
    # Verify database deleted target message
    conn = mock_app_state.db_pool.get_write_connection.return_value.__enter__.return_value
    conn.execute.assert_any_call(
        "DELETE FROM conversation_messages WHERE conversation_id = ? AND created_at >= ?",
        ("c1", mock_app_state.history_store.get_history.return_value[1].created_at.isoformat())
    )
    
    # Verify process_message was called again with previous user query
    args, kwargs = mock_app_state.process_message.call_args
    assert args == ("c1", "what is code?")
