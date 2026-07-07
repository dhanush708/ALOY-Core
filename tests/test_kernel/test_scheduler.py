import pytest
import asyncio
from kernel.scheduler import BackgroundScheduler

@pytest.mark.asyncio
async def test_scheduler_one_shot():
    scheduler = BackgroundScheduler()
    await scheduler.start()
    
    executed = False
    
    async def task():
        nonlocal executed
        executed = True
        
    scheduler.schedule_once("test_task", task, delay_seconds=0.1)
    
    assert not executed
    await asyncio.sleep(0.2)
    assert executed
    
    await scheduler.stop()

@pytest.mark.asyncio
async def test_scheduler_cancel():
    scheduler = BackgroundScheduler()
    await scheduler.start()
    
    executed = False
    
    async def task():
        nonlocal executed
        executed = True
        
    task_id = scheduler.schedule_once("test_task", task, delay_seconds=0.5)
    
    # Cancel before execution
    scheduler.cancel(task_id)
    
    await asyncio.sleep(0.6)
    assert not executed
    
    await scheduler.stop()
