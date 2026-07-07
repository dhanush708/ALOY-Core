import pytest
import asyncio
from datetime import datetime, timezone
from kernel.types import Event
from kernel.event_bus import EventBus

@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    bus = EventBus()
    await bus.start()
    
    received_events = []
    
    async def handler(event):
        received_events.append(event)
        
    bus.subscribe("test.event", handler)
    
    event = Event(type="test.event", data={"key": "value"}, source="test")
    await bus.publish(event)
    
    # Wait for processing
    await asyncio.sleep(0.1)
    
    assert len(received_events) == 1
    assert received_events[0].type == "test.event"
    assert received_events[0].data["key"] == "value"
    
    await bus.stop()

@pytest.mark.asyncio
async def test_event_bus_pattern_subscribe():
    bus = EventBus()
    await bus.start()
    
    received_events = []
    
    async def handler(event):
        received_events.append(event)
        
    bus.subscribe_pattern("agent.*", handler)
    
    await bus.publish(Event(type="agent.started", data={}, source="test"))
    await bus.publish(Event(type="agent.completed", data={}, source="test"))
    await bus.publish(Event(type="system.booted", data={}, source="test"))
    
    await asyncio.sleep(0.1)
    
    assert len(received_events) == 2
    types = {e.type for e in received_events}
    assert "agent.started" in types
    assert "agent.completed" in types
    
    await bus.stop()
    
@pytest.mark.asyncio
async def test_event_bus_error_handling_and_dlq():
    bus = EventBus()
    await bus.start()
    
    fail_count = 0
    
    async def failing_handler(event):
        nonlocal fail_count
        fail_count += 1
        raise ValueError("Simulated failure")
        
    bus.subscribe("fail.event", failing_handler)
    
    # Event with 1 retry max
    event = Event(type="fail.event", data={}, source="test", max_retries=1)
    await bus.publish(event)
    
    # Wait for processing and retries
    await asyncio.sleep(0.2)
    
    # Should be 1 initial attempt + 1 retry = 2 attempts total
    assert fail_count == 2
    
    # Should end up in DLQ
    metrics = bus.get_metrics()
    assert metrics["dead_letter_count"] == 1
    assert len(bus._dead_letter_queue) == 1
    
    await bus.stop()
