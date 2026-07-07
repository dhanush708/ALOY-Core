import pytest
from kernel.service_registry import ServiceRegistry
from typing import Protocol

class ITestService(Protocol):
    def do_something(self) -> str: ...

class TestService:
    def do_something(self) -> str:
        return "done"

def test_service_registry():
    registry = ServiceRegistry()
    service = TestService()
    
    assert not registry.has(ITestService)
    
    registry.register(ITestService, service)
    
    assert registry.has(ITestService)
    
    resolved = registry.get(ITestService)
    assert resolved is service
    assert resolved.do_something() == "done"
    
def test_service_registry_missing():
    registry = ServiceRegistry()
    
    with pytest.raises(KeyError):
        registry.get(ITestService)
