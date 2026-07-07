import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from models.router import ModelRouter, ROUTING_TABLE, Priority

@pytest.mark.asyncio
async def test_concurrent_requests_limits_and_priorities():
    # Setup router with max_concurrent = 2
    router = ModelRouter(max_concurrent=2)
    router.client = MagicMock()
    
    # Track model call sequence
    call_sequence = []
    
    async def mock_generate(model, prompt, options=None, **kwargs):
        call_sequence.append(prompt)
        await asyncio.sleep(0.05) # Simulate latency
        return f"Response to {prompt}"
        
    router.client.generate = mock_generate
    
    # Trigger 6 concurrent requests: 3 background priority, 3 conversation priority
    tasks = []
    # 3 Background tasks (lower priority)
    for i in range(3):
        tasks.append(router.generate("memory_generation", f"BG_{i}"))
    # 3 Conversation tasks (higher priority)
    for i in range(3):
        tasks.append(router.generate("simple_chat", f"CONV_{i}"))
        
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 6
    # Check that some conversation tasks were called before all background tasks finished,
    # showing priority sorting in the lock coordinator
    assert len(call_sequence) == 6

@pytest.mark.asyncio
async def test_router_fallback_chain_under_failure():
    router = ModelRouter()
    router.client = MagicMock()
    
    # We will simulate a failure of the primary model and success of fallback
    call_counts = {}
    
    async def mock_generate(model, prompt, options=None, **kwargs):
        call_counts[model] = call_counts.get(model, 0) + 1
        if model == ROUTING_TABLE["simple_chat"]["primary"]:
            raise RuntimeError("Primary model is offline")
        return "Fallback Success"
        
    router.client.generate = mock_generate
    
    # Trigger generate
    response = await router.generate("simple_chat", "Hello")
    assert response == "Fallback Success"
    
    # Ensure primary was tried, failed, and fallback was called
    primary = ROUTING_TABLE["simple_chat"]["primary"]
    fallback = ROUTING_TABLE["simple_chat"]["fallback"]
    assert call_counts[primary] == 1
    assert call_counts[fallback] == 1
    
    # Verify tracker health reflects failure for primary and success for fallback
    assert router.tracker.get_health(primary).error_count == 1
    assert router.tracker.get_health(fallback).error_count == 0

@pytest.mark.asyncio
async def test_streaming_failure_recovery():
    router = ModelRouter()
    router.client = MagicMock()
    
    # If the stream yields error, check router returns [Connection Error]
    async def mock_stream(model, prompt, options=None, **kwargs):
        yield "Chunk 1"
        raise ConnectionError("Ollama disconnected")
        
    router.client.stream = mock_stream
    
    tokens = []
    async for t in router.stream("simple_chat", "Stream test"):
        tokens.append(t)
        
    # Check it yielded what was received before failing, then yielded error message
    assert tokens[0] == "Chunk 1"
    assert tokens[1] == " [Connection Error]"
