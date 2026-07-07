import asyncio
import logging
import uuid
from typing import Callable, Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class ScheduledTask:
    def __init__(
        self,
        name: str,
        func: Callable,
        interval_seconds: float = 0,
        delay_seconds: float = 0,
        is_periodic: bool = False
    ):
        self.id = str(uuid.uuid4())
        self.name = name
        self.func = func
        self.interval_seconds = interval_seconds
        self.delay_seconds = delay_seconds
        self.is_periodic = is_periodic
        
        self.last_run_at: Optional[datetime] = None
        self.status = "active"
        self._task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()

    async def _run_periodic(self):
        try:
            if self.delay_seconds > 0:
                await asyncio.sleep(self.delay_seconds)
                
            while not self._cancel_event.is_set():
                try:
                    await self.func()
                    self.last_run_at = datetime.now(timezone.utc)
                except Exception as e:
                    logger.error(f"Error in periodic task {self.name}: {e}", exc_info=True)
                    
                # We use wait() with a timeout so it can be interrupted promptly
                try:
                    await asyncio.wait_for(self._cancel_event.wait(), timeout=self.interval_seconds)
                except asyncio.TimeoutError:
                    pass # Timeout expected
        except asyncio.CancelledError:
            self.status = "cancelled"

    async def _run_once(self):
        try:
            if self.delay_seconds > 0:
                # Wait for delay, but allow cancellation
                try:
                    await asyncio.wait_for(self._cancel_event.wait(), timeout=self.delay_seconds)
                    if self._cancel_event.is_set():
                        return
                except asyncio.TimeoutError:
                    pass
                    
            if not self._cancel_event.is_set():
                try:
                    await self.func()
                    self.last_run_at = datetime.now(timezone.utc)
                except Exception as e:
                    logger.error(f"Error in delayed task {self.name}: {e}", exc_info=True)
            self.status = "completed"
        except asyncio.CancelledError:
            self.status = "cancelled"
            
    def start(self):
        if self.is_periodic:
            self._task = asyncio.create_task(self._run_periodic())
        else:
            self._task = asyncio.create_task(self._run_once())
            
    def cancel(self):
        self.status = "cancelled"
        self._cancel_event.set()
        if self._task:
            self._task.cancel()

class BackgroundScheduler:
    """Unified background task scheduler."""
    
    def __init__(self):
        self._tasks: Dict[str, ScheduledTask] = {}
        
    async def start(self):
        logger.info("Background scheduler started.")
        
    async def stop(self):
        for task in self._tasks.values():
            task.cancel()
        logger.info("Background scheduler stopped.")
        
    def schedule_periodic(self, name: str, func: Callable, interval_seconds: float, delay_seconds: float = 0) -> str:
        """Schedule a task to run periodically."""
        task = ScheduledTask(
            name=name,
            func=func,
            interval_seconds=interval_seconds,
            delay_seconds=delay_seconds,
            is_periodic=True
        )
        self._tasks[task.id] = task
        task.start()
        logger.debug(f"Scheduled periodic task {name} ({interval_seconds}s interval)")
        return task.id
        
    def schedule_once(self, name: str, func: Callable, delay_seconds: float) -> str:
        """Schedule a one-shot delayed task."""
        task = ScheduledTask(
            name=name,
            func=func,
            delay_seconds=delay_seconds,
            is_periodic=False
        )
        self._tasks[task.id] = task
        task.start()
        logger.debug(f"Scheduled one-shot task {name} ({delay_seconds}s delay)")
        return task.id
        
    def cancel(self, task_id: str) -> bool:
        """Cancel a scheduled task."""
        if task_id in self._tasks:
            self._tasks[task_id].cancel()
            del self._tasks[task_id]
            return True
        return False
        
    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all tasks."""
        return [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "is_periodic": t.is_periodic,
                "interval_seconds": t.interval_seconds,
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None
            }
            for t in self._tasks.values()
        ]
