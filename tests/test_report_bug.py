import pytest
from fastapi.testclient import TestClient
from api.server import app, _app_data
import os
from pathlib import Path
import smtplib

client = TestClient(app)

def test_report_bug_endpoint_success_fallback():
    # Since there is no actual SMTP server on port 25 during test, it should fallback to local file
    payload = {
        "title": "Test Bug",
        "description": "Test description",
        "steps_to_reproduce": "1. Test",
        "expected_behavior": "Test expected",
        "actual_behavior": "Test actual",
        "system_information": "Test System Info v1.0.2"
    }
    
    response = client.post("/api/system/report-bug", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "Report saved locally."
    assert "path" in data
    
    # Verify file was created
    file_path = Path(data["path"])
    assert file_path.exists()
    
    # Verify content
    content = file_path.read_text(encoding="utf-8")
    assert "Test Bug" in content
    assert "Test description" in content
    assert "Test System Info v1.0.2" in content
    
    # Cleanup
    file_path.unlink()

def test_report_bug_endpoint_success_email(monkeypatch):
    # Mock SMTP to simulate email success
    class MockSMTP:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def send_message(self, msg):
            pass
            
    monkeypatch.setattr(smtplib, "SMTP", MockSMTP)
    
    payload = {
        "title": "Test Email Bug",
        "description": "Test email description",
        "steps_to_reproduce": "1. Email Test",
        "expected_behavior": "Email Expected",
        "actual_behavior": "Email Actual",
        "system_information": "Test System Info v1.0.2"
    }
    
    response = client.post("/api/system/report-bug", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "Report sent via email."
    assert data["path"] is None
