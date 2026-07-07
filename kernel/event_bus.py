import asyncio
import logging
import uuid
import fnmatch
from typing import Callable, Dict, List, Any, Optional
from datetime import datetime, timezone
from collections import defaultdict
from .types import Event

logger = logging.getLogger(__name__)

class EventBusMetrics:
    def __init__(self):
        self.published_count = 0
        self.processed_count = 0
        self.error_count = 0
        self.dead_letter_count = 0
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "published_count": self.published_count,
            "processed_count": self.processed_count,
            "error_count": self.error_count,
            "dead_letter_count": self.dead_letter_count,
        }

class EventBus:
    """Async Event Bus with error handling, dead letter queue, and priorities."""
    
    def __init__(self):
        # type -> [(sub_id, handler)]
        self._subscribers: Dict[str, List[tuple[str, Callable]]] = defaultdict(list)
        # pattern -> [(sub_id, handler)]
        self._pattern_subscribers: Dict[str, List[tuple[str, Callable]]] = defaultdict(list)
        
        self._queue = asyncio.PriorityQueue()
        self._dead_letter_queue: List[Event] = []
        self._worker_task: Optional[asyncio.Task] = None
        self._metrics = EventBusMetrics()
        
    async def start(self):
        """Start the background worker to process events."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._process_events())
            logger.info("Event bus started.")
            
    async def stop(self):
        """Stop the event bus gracefully."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("Event bus stopped.")
            
    def subscribe(self, event_type: str, handler: Callable) -> str:
        """Subscribe to an exact event type. Returns subscription ID."""
        sub_id = str(uuid.uuid4())
        self._subscribers[event_type].append((sub_id, handler))
        return sub_id
        
    def subscribe_pattern(self, pattern: str, handler: Callable) -> str:
        """Subscribe to a pattern (e.g. 'agent.*'). Returns subscription ID."""
        sub_id = str(uuid.uuid4())
        self._pattern_subscribers[pattern].append((sub_id, handler))
        return sub_id
        
    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by ID."""
        for event_type, subs in list(self._subscribers.items()):
            self._subscribers[event_type] = [(sid, h) for sid, h in subs if sid != subscription_id]
            
        for pattern, subs in list(self._pattern_subscribers.items()):
            self._pattern_subscribers[pattern] = [(sid, h) for sid, h in subs if sid != subscription_id]
            
    async def publish(self, event: Event) -> None:
        """Publish an event asynchronously."""
        # Note: asyncio.PriorityQueue gets lowest number first, so we invert priority
        # 2 (critical) becomes -2, 1 (high) becomes -1, 0 (normal) becomes 0
        priority_key = -event.priority
        await self._queue.put((priority_key, event.timestamp, id(event), event))
        self._metrics.published_count += 1
        
    async def publish_and_wait(self, event: Event, timeout: float = 30.0) -> List[Any]:
        """Publish an event and wait for all matching handlers to complete (synchronous flow)."""
        handlers = self._get_handlers_for_event(event.type)
        self._metrics.published_count += 1
        
        if not handlers:
            return []
            
        results = []
        for _, handler in handlers:
            try:
                res = handler(event)
                if asyncio.iscoroutine(res):
                    result = await asyncio.wait_for(res, timeout=timeout)
                else:
                    result = res
                results.append(result)
                self._metrics.processed_count += 1
            except Exception as e:
                logger.error(f"Error in synchronous event handler for {event.type}: {e}")
                self._metrics.error_count += 1
                
        return results
        
    def get_metrics(self) -> Dict[str, Any]:
        """Return event bus metrics."""
        m = self._metrics.to_dict()
        m["queue_size"] = self._queue.qsize()
        return m
        
    async def replay(self, event_type: str, since: datetime) -> List[Event]:
        """Replay events from the dead letter queue matching criteria."""
        replayed = []
        remaining_dlq = []
        for event in self._dead_letter_queue:
            if (event_type == "*" or event.type == event_type) and event.timestamp >= since:
                event.retry_count = 0  # reset retries
                await self.publish(event)
                replayed.append(event)
            else:
                remaining_dlq.append(event)
                
        self._dead_letter_queue = remaining_dlq
        return replayed

    def _get_handlers_for_event(self, event_type: str) -> List[tuple[str, Callable]]:
        """Get all handlers (exact and pattern matched) for an event type."""
        handlers = list(self._subscribers.get(event_type, []))
        for pattern, subs in self._pattern_subscribers.items():
            if fnmatch.fnmatch(event_type, pattern):
                handlers.extend(subs)
        return handlers
        
    async def _process_events(self):
        """Background worker to process events from the priority queue."""
        while True:
            try:
                _, _, _, event = await self._queue.get()
                
                if event.is_expired():
                    logger.debug(f"Event {event.id} ({event.type}) expired, dropping.")
                    self._queue.task_done()
                    continue
                    
                handlers = self._get_handlers_for_event(event.type)
                
                for _, handler in handlers:
                    try:
                        res = handler(event)
                        if asyncio.iscoroutine(res):
                            await res
                        self._metrics.processed_count += 1
                    except Exception as e:
                        logger.error(f"Error processing event {event.type}: {e}", exc_info=True)
                        self._metrics.error_count += 1
                        
                        # Handle retries
                        event.retry_count += 1
                        if event.retry_count <= event.max_retries:
                            logger.info(f"Retrying event {event.id} ({event.retry_count}/{event.max_retries})")
                            # Add back to queue with slightly lower priority
                            await self._queue.put((-event.priority, datetime.now(timezone.utc), id(event), event))
                        else:
                            logger.error(f"Event {event.id} max retries exceeded, sending to DLQ.")
                            self._dead_letter_queue.append(event)
                            self._metrics.dead_letter_count += 1
                            
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fatal error in event bus worker: {e}", exc_info=True)
                await asyncio.sleep(1) # Prevent tight loop on fatal queue error
