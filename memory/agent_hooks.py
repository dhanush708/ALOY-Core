"""
memory/agent_hooks.py
---------------------
AgentMemoryHooks: typed memory recording interface for the Agent Runtime.

Records agent events as structured memories with canonical tags and
high agent_signal so the extended importance scorer boosts them appropriately.

Canonical tags:
  agent:success  — task completed successfully
  agent:failure  — task failed
  agent:bug      — a bug was discovered
  agent:fix      — a bug was resolved
  agent:strategy — a useful strategy was identified
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Canonical tag prefixes used by agent hooks
TAG_SUCCESS  = "agent:success"
TAG_FAILURE  = "agent:failure"
TAG_BUG      = "agent:bug"
TAG_FIX      = "agent:fix"
TAG_STRATEGY = "agent:strategy"


class AgentMemoryHooks:
    """
    High-level interface for Agent Runtime to record memorable events.

    Each method creates a Memory via MemoryManager and attaches canonical tags
    via TagManager so that retrieval profiles for "coding" and "planning"
    can surface them efficiently.
    """

    def __init__(self, memory_manager, tag_manager, collection_mgr):
        self._mem   = memory_manager
        self._tags  = tag_manager
        self._cols  = collection_mgr

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _store_and_tag(
        self,
        content: str,
        memory_type: str,
        tags: list,
        workspace_id: Optional[str],
        agent_signal: float = 0.8,
        importance: float = 0.7,
        tier: str = "long_term",
        metadata: Optional[dict] = None,
    ) -> str:
        """Store a memory, tag it, and optionally add it to a workspace collection."""
        meta = metadata or {}
        meta["agent_signal"] = agent_signal

        mem = await self._mem.store(
            type=memory_type,
            content=content,
            tier=tier,
            importance=importance,
            metadata=meta,
        )
        self._tags.add_tags(mem.id, tags)

        if workspace_id:
            col = self._cols.find_or_create_workspace_collection(workspace_id)
            self._cols.add_memory(col.id, mem.id)

        return mem.id

    # ------------------------------------------------------------------
    # Public recording API
    # ------------------------------------------------------------------

    async def record_success(
        self,
        task: str,
        outcome: str,
        workspace_id: Optional[str] = None,
        extra_tags: Optional[list] = None,
    ) -> str:
        """Record a successfully completed agent task."""
        content = f"[SUCCESS] Task: {task}\nOutcome: {outcome}"
        tags = [TAG_SUCCESS] + (extra_tags or [])
        logger.debug(f"AgentMemoryHooks.record_success: {task[:60]}")
        return await self._store_and_tag(
            content=content,
            memory_type="agent_event",
            tags=tags,
            workspace_id=workspace_id,
            agent_signal=0.9,
            importance=0.75,
        )

    async def record_failure(
        self,
        task: str,
        error: str,
        workspace_id: Optional[str] = None,
        extra_tags: Optional[list] = None,
    ) -> str:
        """Record a failed agent task so future agents can avoid similar mistakes."""
        content = f"[FAILURE] Task: {task}\nError: {error}"
        tags = [TAG_FAILURE] + (extra_tags or [])
        logger.debug(f"AgentMemoryHooks.record_failure: {task[:60]}")
        return await self._store_and_tag(
            content=content,
            memory_type="agent_event",
            tags=tags,
            workspace_id=workspace_id,
            agent_signal=0.85,
            importance=0.80,   # failures are more important to remember
        )

    async def record_bug(
        self,
        description: str,
        file_path: Optional[str] = None,
        workspace_id: Optional[str] = None,
        extra_tags: Optional[list] = None,
    ) -> str:
        """Record a discovered bug."""
        location = f"\nFile: {file_path}" if file_path else ""
        content = f"[BUG] {description}{location}"
        tags = [TAG_BUG] + (extra_tags or [])
        if file_path:
            tags.append(f"file:{file_path.split('/')[-1]}")
        logger.debug(f"AgentMemoryHooks.record_bug: {description[:60]}")
        return await self._store_and_tag(
            content=content,
            memory_type="agent_bug",
            tags=tags,
            workspace_id=workspace_id,
            agent_signal=0.90,
            importance=0.82,
        )

    async def record_fix(
        self,
        bug_description: str,
        solution: str,
        workspace_id: Optional[str] = None,
        extra_tags: Optional[list] = None,
    ) -> str:
        """Record the solution to a bug so it can be reused."""
        content = f"[FIX] Bug: {bug_description}\nSolution: {solution}"
        tags = [TAG_FIX, TAG_STRATEGY] + (extra_tags or [])
        logger.debug(f"AgentMemoryHooks.record_fix: {bug_description[:60]}")
        return await self._store_and_tag(
            content=content,
            memory_type="agent_fix",
            tags=tags,
            workspace_id=workspace_id,
            agent_signal=0.95,
            importance=0.85,
            tier="long_term",
        )

    async def record_strategy(
        self,
        name: str,
        description: str,
        domain: Optional[str] = None,
        workspace_id: Optional[str] = None,
        extra_tags: Optional[list] = None,
    ) -> str:
        """Record a reusable strategy or pattern."""
        domain_str = f"\nDomain: {domain}" if domain else ""
        content = f"[STRATEGY] {name}{domain_str}\n{description}"
        tags = [TAG_STRATEGY] + (extra_tags or [])
        if domain:
            tags.append(f"domain:{domain}")
        logger.debug(f"AgentMemoryHooks.record_strategy: {name}")
        return await self._store_and_tag(
            content=content,
            memory_type="strategy",
            tags=tags,
            workspace_id=workspace_id,
            agent_signal=1.0,
            importance=0.90,
            tier="long_term",
        )
