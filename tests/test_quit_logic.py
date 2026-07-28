import pytest
from fastapi.testclient import TestClient
from api.server import app
from pathlib import Path
import threading
import time

client = TestClient(app)

def test_quit_endpoint_cleans_up_and_shuts_down(monkeypatch, tmp_path):
    # Mock the DB pool and scheduler
    class MockDBPool:
        def __init__(self):
            self.closed = False
        def close(self):
            self.closed = True

    class MockScheduler:
        def __init__(self):
            self.shutdown_called = False
        def shutdown(self):
            self.shutdown_called = True
            
    class MockServer:
        def __init__(self):
            self.should_exit = False

    app.state.db_pool = MockDBPool()
    app.state.scheduler = MockScheduler()
    app.state.server = MockServer()
    
    # Mock lockfile
    import api.server as server_module
    lockfile_path = tmp_path / "running.tmp"
    lockfile_path.write_text("running")
    monkeypatch.setattr(server_module, "LOCK_FILE", str(lockfile_path))
    
    # Fast-forward the sleep
    monkeypatch.setattr(time, "sleep", lambda x: None)

    # Call endpoint
    response = client.post("/api/system/quit")
    
    # Browser receives success response
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # The endpoint launches a thread, wait a tiny bit for it to run our mocked logic
    time.sleep(0.1)
    
    # Cleanup executes
    assert app.state.db_pool.closed is True
    assert app.state.scheduler.shutdown_called is True
    
    # Lockfile removed
    assert not lockfile_path.exists()
    
    # Server shutdown triggered
    assert app.state.server.should_exit is True
