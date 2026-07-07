import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from api.server import app

@pytest.fixture
def mock_agent_runtime():
    # Mock runtime
    runtime = MagicMock()
    
    # Mock db_pool
    db_pool = MagicMock()
    conn_mock = MagicMock()
    db_pool.get_read_connection.return_value.__enter__.return_value = conn_mock
    runtime.db_pool = db_pool
    
    # Mock async methods
    runtime.start_session = AsyncMock()
    runtime.get_session_status = AsyncMock()
    runtime.execute_session = AsyncMock()
    runtime.pause_session = AsyncMock()
    runtime.resume_session = AsyncMock()
    runtime.resume_session_from_checkpoint = AsyncMock()
    runtime.rollback_session = AsyncMock()
    
    # Mock task queue
    task_queue = MagicMock()
    task_queue.list_tasks = AsyncMock()
    runtime.task_queue = task_queue
    
    # Attach to app.state
    app.state.agent_runtime = runtime
    return runtime

def test_list_sessions(mock_agent_runtime):
    conn = mock_agent_runtime.db_pool.get_read_connection.return_value.__enter__.return_value
    conn.execute.return_value.fetchall.return_value = [
        ("s1", "p1", "Test goal 1", "planning", "2026-06-23T12:00:00", "2026-06-23T12:05:00"),
        ("s2", "p2", "Test goal 2", "completed", "2026-06-23T11:00:00", "2026-06-23T11:30:00")
    ]
    
    client = TestClient(app)
    response = client.get("/api/agent/sessions")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["session_id"] == "s1"
    assert data[0]["goal"] == "Test goal 1"
    assert data[0]["status"] == "planning"

def test_create_session(mock_agent_runtime):
    mock_agent_runtime.start_session.return_value = "new-session-id"
    
    client = TestClient(app)
    response = client.post("/api/agent/session", json={
        "goal": "Write a python calculator",
        "project_id": "proj-1"
    })
    
    assert response.status_code == 200
    assert response.json()["session_id"] == "new-session-id"
    mock_agent_runtime.start_session.assert_called_with("Write a python calculator", "proj-1")

def test_get_session_status(mock_agent_runtime):
    mock_agent_runtime.get_session_status.return_value = {
        "session_id": "s1",
        "goal": "Test goal 1",
        "status": "executing",
        "checkpoints": []
    }
    
    client = TestClient(app)
    response = client.get("/api/agent/session/s1")
    
    assert response.status_code == 200
    assert response.json()["status"] == "executing"
    mock_agent_runtime.get_session_status.assert_called_with("s1")

def test_get_session_status_not_found(mock_agent_runtime):
    mock_agent_runtime.get_session_status.return_value = None
    
    client = TestClient(app)
    response = client.get("/api/agent/session/non-existent")
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_execute_session(mock_agent_runtime):
    mock_agent_runtime.execute_session.return_value = None
    
    client = TestClient(app)
    response = client.post("/api/agent/session/s1/execute")
    
    assert response.status_code == 200
    assert response.json()["status"] == "execution_started"
    mock_agent_runtime.execute_session.assert_called_with("s1")

def test_pause_session(mock_agent_runtime):
    mock_agent_runtime.pause_session.return_value = None
    
    client = TestClient(app)
    response = client.post("/api/agent/session/s1/pause")
    
    assert response.status_code == 200
    assert response.json()["status"] == "paused"
    mock_agent_runtime.pause_session.assert_called_with("s1")

def test_resume_session(mock_agent_runtime):
    mock_agent_runtime.resume_session.return_value = None
    
    client = TestClient(app)
    response = client.post("/api/agent/session/s1/resume")
    
    assert response.status_code == 200
    assert response.json()["status"] == "resumed"
    mock_agent_runtime.resume_session.assert_called_with("s1")

def test_resume_session_from_checkpoint(mock_agent_runtime):
    mock_agent_runtime.resume_session_from_checkpoint.return_value = None
    
    client = TestClient(app)
    response = client.post("/api/agent/session/s1/resume-from-checkpoint", json={
        "checkpoint_id": "chk-1"
    })
    
    assert response.status_code == 200
    assert response.json()["status"] == "resume_started"
    mock_agent_runtime.resume_session_from_checkpoint.assert_called_with("s1", "chk-1")

def test_rollback_session(mock_agent_runtime):
    mock_agent_runtime.rollback_session.return_value = None
    
    client = TestClient(app)
    response = client.post("/api/agent/session/s1/rollback", json={
        "checkpoint_id": "chk-1"
    })
    
    assert response.status_code == 200
    assert response.json()["status"] == "rolled_back"
    mock_agent_runtime.rollback_session.assert_called_with("s1", "chk-1")

def test_list_tasks(mock_agent_runtime):
    task_mock = MagicMock()
    task_mock.id = "t1"
    task_mock.title = "Task 1"
    task_mock.description = "Desc 1"
    task_mock.assigned_agent = "coder"
    task_mock.priority = 1
    task_mock.status.value = "done"
    task_mock.depends_on = []
    task_mock.result = "Success"
    task_mock.error = None
    task_mock.created_at = "2026-06-23T12:00:00"
    task_mock.updated_at = "2026-06-23T12:05:00"
    
    mock_agent_runtime.task_queue.list_tasks.return_value = [task_mock]
    
    client = TestClient(app)
    response = client.get("/api/agent/session/s1/tasks")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "t1"
    assert data[0]["title"] == "Task 1"
    assert data[0]["status"] == "done"
    mock_agent_runtime.task_queue.list_tasks.assert_called_with("s1")
