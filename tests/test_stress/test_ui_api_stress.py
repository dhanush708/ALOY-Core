import pytest
import threading
from fastapi.testclient import TestClient
from api.server import app

def test_api_concurrent_requests_stress():
    # TestClient is synchronous, so we can run it in multiple threads to stress test the server endpoints.
    # We run it inside the 'with' context manager to ensure the FastAPI lifespan (db_pool init) runs first.
    with TestClient(app) as client:
        errors = []
        def hit_health():
            try:
                response = client.get("/health")
                if response.status_code != 200:
                    errors.append(f"Health failed: {response.status_code}")
            except Exception as e:
                errors.append(f"Health exception: {e}")
                
        def hit_telemetry():
            try:
                response = client.get("/api/system/metrics")
                if response.status_code != 200:
                    errors.append(f"Telemetry failed: {response.status_code}")
            except Exception as e:
                errors.append(f"Telemetry exception: {e}")
                
        # Launch 20 concurrent request threads (10 health, 10 telemetry)
        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=hit_health))
            threads.append(threading.Thread(target=hit_telemetry))
            
        for t in threads:
            t.start()
            
        for t in threads:
            t.join()
            
        assert len(errors) == 0, f"Concurrent requests had errors: {errors}"
