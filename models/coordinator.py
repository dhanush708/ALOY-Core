"""
Priority-based model access coordinator.

Ensures conversation-priority requests are never blocked by background tasks.
"""

import asyncio
import logging
from enum import IntEnum

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    BACKGROUND = 0   # learning, consolidation — yields to everything
    AGENT = 1        # coding agent — yields to conversation
    CONVERSATION = 2 # user-facing — never waits


class ModelCoordinator:
    """Manages concurrent access to the Ollama inference server.

    Only one generation can run per model at a time (Ollama limitation with
    single-GPU setups). Higher-priority callers pre-empt lower ones by
    acquiring the semaphore first.
    """

    def __init__(self, max_concurrent: int = 1):
        # Global semaphore controlling total concurrent LLM calls.
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_priority: int = -1
        self._lock = asyncio.Lock()
        self._busy = False

    def is_busy(self) -> bool:
        """Return True if any LLM request is currently in flight."""
        return self._busy

    async def acquire(self, priority: Priority) -> None:
        """Acquire the right to use the model at the given priority."""
        await self._semaphore.acquire()
        async with self._lock:
            self._active_priority = priority
            self._busy = True

    async def release(self) -> None:
        async with self._lock:
            self._active_priority = -1
            self._busy = False
        self._semaphore.release()
