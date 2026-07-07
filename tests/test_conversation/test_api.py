import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from api.server import app, lifespan

# Note: Testing FastAPI lifespan with TestClient can be tricky.
# We'll use the TestClient inside an async test or mock dependencies.
# Since app initialization requires DB, we'll patch the app state directly for unit testing routes.

@pytest.fixture
def mock_app_state():
    from unittest.mock import AsyncMock, MagicMock
    app.state.engine = MagicMock()
    app.state.engine.get_or_create_state = AsyncMock()
    app.state.engine.process_message = AsyncMock()
    app.state.engine.history_store = MagicMock()
    app.state.engine.history_store.get_conversation = AsyncMock()
    app.state.engine.history_store.get_history = AsyncMock()
    return app.state.engine

def test_create_conversation(mock_app_state):
    from conversation.state import ConversationState
    mock_app_state.get_or_create_state.return_value = ConversationState(id="123")
    
    client = TestClient(app)
    response = client.post("/api/conversation")
    
    assert response.status_code == 200
    assert response.json()["id"] == "123"

def test_get_history(mock_app_state):
    from conversation.history import ConversationMessage
    from datetime import datetime, timezone
    
    mock_app_state.history_store.get_history.return_value = [
        ConversationMessage(id="m1", conversation_id="123", role="user", content="hello", created_at=datetime.now(timezone.utc), metadata={})
    ]
    
    client = TestClient(app)
    response = client.get("/api/conversation/123/history")
    
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["content"] == "hello"
