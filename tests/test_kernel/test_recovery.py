import pytest
from kernel.recovery import ErrorRecovery

@pytest.mark.asyncio
async def test_error_recovery_success():
    recovery = ErrorRecovery()
    
    calls = 0
    async def success_func():
        nonlocal calls
        calls += 1
        return "success"
        
    result = await recovery.with_retry(success_func)
    
    assert result == "success"
    assert calls == 1

@pytest.mark.asyncio
async def test_error_recovery_retry_success():
    recovery = ErrorRecovery()
    
    calls = 0
    async def fail_then_succeed():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("Failed")
        return "success"
        
    result = await recovery.with_retry(
        fail_then_succeed, 
        max_retries=3, 
        backoff_strategy="none",
        base_delay_seconds=0.01
    )
    
    assert result == "success"
    assert calls == 3

@pytest.mark.asyncio
async def test_error_recovery_fallback():
    recovery = ErrorRecovery()
    
    async def always_fail():
        raise ValueError("Failed")
        
    async def fallback():
        return "fallback"
        
    result = await recovery.with_retry(
        always_fail,
        max_retries=1,
        backoff_strategy="none",
        base_delay_seconds=0.01,
        fallback=fallback
    )
    
    assert result == "fallback"
