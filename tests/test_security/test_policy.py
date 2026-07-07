import pytest
from security.policy import PolicyEngine

@pytest.mark.asyncio
async def test_policy_engine_system_actor():
    engine = PolicyEngine(db_pool=None)
    
    decision = await engine.evaluate("write", "sensitive_file.txt", {"actor": "system"})
    assert decision.allowed is True
    assert decision.requires_approval is False

@pytest.mark.asyncio
async def test_policy_engine_read_action():
    engine = PolicyEngine(db_pool=None)
    
    decision = await engine.evaluate("read", "file.txt", {"actor": "user"})
    assert decision.allowed is True
    assert decision.requires_approval is False

@pytest.mark.asyncio
async def test_policy_engine_write_action():
    engine = PolicyEngine(db_pool=None)
    
    decision = await engine.evaluate("write", "file.txt", {"actor": "user"})
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.auto_approve_for_session is True
