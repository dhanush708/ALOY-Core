import logging
import uuid
from typing import List, Optional, Dict, Any

from .types import Memory, ScoredMemory
from .store import MemoryStore
from .working import WorkingMemory
from .importance import ImportanceScorer
from .decay import DecayEngine
from .retrieval import RetrievalEngine
from .linking import MemoryLinker
from .vector_store import VectorStore
from .embeddings import EmbeddingEngine
from .tags import TagManager
from .collections import CollectionManager
from .compression import MemoryCompressor
from .clustering import SemanticClusterer
from .consolidation import ConsolidationEngine
from .profiles import RetrievalProfileEngine, RetrievalProfile
from .context_pack import ContextPackBuilder
from .agent_hooks import AgentMemoryHooks
from .knowledge_hooks import KnowledgeMemoryBridge

logger = logging.getLogger(__name__)


class MemoryManager:
    """Orchestrates all memory operations."""

    def __init__(self, db_pool, telemetry=None):
        self.db_pool = db_pool
        self.telemetry = telemetry

        # -- Core --
        self._store       = MemoryStore(db_pool)
        self.vector_store = VectorStore(db_pool)
        self.embeddings   = EmbeddingEngine()
        self.working      = WorkingMemory()
        self.scorer       = ImportanceScorer()
        self.decay_engine = DecayEngine(db_pool)
        self.retrieval    = RetrievalEngine(db_pool, self._store)
        self.linker       = MemoryLinker(db_pool, self._store)

        # -- Mission 9 extensions --
        self.tags         = TagManager(db_pool)
        self.collections  = CollectionManager(db_pool)
        self.compressor   = MemoryCompressor(db_pool)
        self.clusterer    = SemanticClusterer(db_pool)
        self.consolidation = ConsolidationEngine(
            db_pool=db_pool,
            compressor=self.compressor,
            tag_manager=self.tags,
            clusterer=self.clusterer,
        )
        self.profiles     = RetrievalProfileEngine(
            retrieval_engine=self.retrieval,
            tag_manager=self.tags,
        )
        self.context_pack = ContextPackBuilder(
            retrieval_engine=self.retrieval,
            profile_engine=self.profiles,
            linker=self.linker,
            collection_mgr=self.collections,
            tag_manager=self.tags,
        )
        self.agent_hooks  = AgentMemoryHooks(self, self.tags, self.collections)
        self.knowledge    = KnowledgeMemoryBridge(self, self.tags)

        # -- Retrieval Cache --
        self._retrieval_cache = {}
        self._retrieval_cache_keys = []
        self._max_retrieval_cache_size = 100

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        logger.info("Memory Manager started.")
        # Background decay scheduling is handled by the kernel scheduler.

    async def stop(self):
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _update_embedding(self, memory_id: str, content: str):
        """Generate and save embedding in background."""
        emb = await self.embeddings.generate(content)
        if emb:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute("SELECT rowid FROM memories WHERE id = ?", (memory_id,))
                row = cursor.fetchone()
                if row:
                    await self.vector_store.upsert_embedding(row["rowid"], emb)

    # ------------------------------------------------------------------
    # Core CRUD (unchanged API)
    # ------------------------------------------------------------------

    async def store(
        self,
        type: str,
        content: str,
        tier: str = 'short_term',
        **kwargs
    ) -> Memory:
        """Create and store a new memory."""
        memory_id = str(uuid.uuid4())

        base_importance = kwargs.pop('importance', 0.5)
        importance = self.scorer.score(
            base_importance=base_importance,
            access_count=0,
            last_accessed_at="",
            emotional_weight=kwargs.get("emotional_weight", 0.0),
            relevance=0.5,
            explicit=kwargs.get("is_protected", False)
        )

        mem = Memory(
            id=memory_id,
            type=type,
            content=content,
            tier=tier,
            importance=importance,
            **kwargs
        )

        await self._store.create(mem)
        self._clear_retrieval_cache()
        import asyncio
        asyncio.create_task(self._update_embedding(mem.id, mem.content))

        return mem

    async def get(self, memory_id: str) -> Optional[Memory]:
        """Get a memory by ID, incrementing its access count."""
        mem = await self._store.get(memory_id)
        if mem:
            await self._store.record_access(memory_id)
        return mem

    async def retrieve(
        self,
        query: str,
        types: Optional[List[str]] = None,
        limit: int = 10,
        tags: Optional[List[str]] = None,
    ) -> List[ScoredMemory]:
        """Hybrid retrieval of memories with LRU caching. Supports optional tag filtering."""
        import asyncio
        import time
        cache_key = (
            query,
            tuple(types) if types else None,
            limit,
            tuple(tags) if tags else None
        )
        
        start_time = time.perf_counter()
        if cache_key in self._retrieval_cache:
            if cache_key in self._retrieval_cache_keys:
                self._retrieval_cache_keys.remove(cache_key)
            self._retrieval_cache_keys.append(cache_key)
            results = self._retrieval_cache[cache_key]
            logger.debug("Memory retrieval cache HIT")
            if self.telemetry:
                self.telemetry.record_counter("memory.cache_hit", 1)
        else:
            logger.debug("Memory retrieval cache MISS")
            results = await self.retrieval.retrieve(query, types, limit, tags=tags)
            
            # Store in cache
            self._retrieval_cache[cache_key] = results
            self._retrieval_cache_keys.append(cache_key)
            if len(self._retrieval_cache_keys) > self._max_retrieval_cache_size:
                oldest = self._retrieval_cache_keys.pop(0)
                self._retrieval_cache.pop(oldest, None)
                
            if self.telemetry:
                self.telemetry.record_counter("memory.cache_miss", 1)
                
        duration_ms = (time.perf_counter() - start_time) * 1000
        if self.telemetry:
            self.telemetry.record_memory_retrieval(query, len(results), duration_ms, "hybrid")
                
        # Record access asynchronously in background to avoid blocking retrieval
        for r in results:
            asyncio.create_task(self._store.record_access(r.memory.id))
            
        return results

    async def update(self, memory_id: str, **kwargs) -> Optional[Memory]:
        """Update a memory."""
        await self._store.update(memory_id, kwargs)
        self._clear_retrieval_cache()
        if "content" in kwargs:
            import asyncio
            asyncio.create_task(self._update_embedding(memory_id, kwargs["content"]))
        return await self._store.get(memory_id)

    async def delete(self, memory_id: str, force: bool = False) -> bool:
        """Delete a memory."""
        success = await self._store.delete(memory_id, force)
        if success:
            self._clear_retrieval_cache()
        return success

    async def protect_memory(self, memory_id: str, is_protected: bool = True) -> bool:
        """Mark a memory as protected (preventing automatic decay and deletion)."""
        try:
            await self.update(memory_id, is_protected=1 if is_protected else 0)
            logger.info(f"Memory {memory_id} protection set to {is_protected}")
            return True
        except Exception as e:
            logger.error(f"Failed to set memory protection for {memory_id}: {e}")
            return False

    async def link(
        self, source_id: str, target_id: str, link_type: str, weight: float = 1.0
    ) -> None:
        """Link two memories."""
        await self.linker.link(source_id, target_id, link_type, weight)
        self._clear_retrieval_cache()

    async def get_linked(self, memory_id: str, link_type: str = None) -> List[Memory]:
        """Get directly linked memories."""
        return await self.linker.get_linked(memory_id, link_type)

    async def process_decay(self) -> dict:
        """Manually trigger decay processing."""
        decayed, archived = await self.decay_engine.process_decay()
        if decayed or archived:
            self._clear_retrieval_cache()
        return {"decayed": decayed, "archived": archived}

    # ------------------------------------------------------------------
    # Mission 9: Workspace-scoped memory APIs
    # ------------------------------------------------------------------

    async def store_workspace_memory(
        self,
        workspace_id: str,
        type: str,
        content: str,
        extra_tags: Optional[List[str]] = None,
        **kwargs
    ) -> Memory:
        """
        Store a memory scoped to a workspace.

        Automatically adds a ``workspace:<workspace_id>`` tag and places the
        memory into the default workspace collection.
        """
        mem = await self.store(type=type, content=content, **kwargs)
        ws_tag = f"workspace:{workspace_id}"
        tags = [ws_tag] + (extra_tags or [])
        self.tags.add_tags(mem.id, tags)

        col = self.collections.find_or_create_workspace_collection(workspace_id)
        self.collections.add_memory(col.id, mem.id)

        return mem

    async def retrieve_workspace_memory(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        types: Optional[List[str]] = None,
    ) -> List[ScoredMemory]:
        """
        Retrieve memories scoped to a workspace.

        Uses the ``workspace:<workspace_id>`` tag to pre-filter, then runs
        full hybrid retrieval on the filtered set.
        """
        ws_tag = f"workspace:{workspace_id}"
        return await self.retrieve(query=query, types=types, limit=limit, tags=[ws_tag])

    # ------------------------------------------------------------------
    # Mission 9: Profile-tuned retrieval
    # ------------------------------------------------------------------

    async def retrieve_with_profile(
        self,
        query: str,
        profile: RetrievalProfile,
        limit: Optional[int] = None,
        extra_tags: Optional[List[str]] = None,
    ) -> List[ScoredMemory]:
        """Retrieve memories using a named retrieval profile."""
        return await self.profiles.retrieve(
            query=query,
            profile=profile,
            limit=limit,
            extra_tags=extra_tags,
        )

    # ------------------------------------------------------------------
    # Mission 9: Graph traversal
    # ------------------------------------------------------------------

    async def get_neighbors(
        self,
        memory_id: str,
        max_hops: int = 2,
        link_type: Optional[str] = None,
    ) -> List[Memory]:
        """BFS graph traversal returning up to 2 hops of linked memories."""
        return await self.linker.get_neighbors(
            memory_id, max_hops=max_hops, link_type=link_type
        )

    async def auto_link(
        self,
        memory_id: str,
        candidate_ids: List[str],
        threshold: float = 0.75,
    ) -> int:
        """Auto-link by cosine similarity. Returns count of new links."""
        count = await self.linker.auto_link(memory_id, candidate_ids, threshold)
        if count > 0:
            self._clear_retrieval_cache()
        return count

    def _clear_retrieval_cache(self):
        self._retrieval_cache.clear()
        self._retrieval_cache_keys.clear()

    # ------------------------------------------------------------------
    # Mission 9: Consolidation
    # ------------------------------------------------------------------

    async def consolidate(self) -> dict:
        """Run a full consolidation cycle (promote, compress, deduplicate, cluster)."""
        res = await self.consolidation.consolidate()
        self._clear_retrieval_cache()
        return res

    # ------------------------------------------------------------------
    # Mission 9: Context Pack
    # ------------------------------------------------------------------

    async def build_context_pack(
        self,
        query: str,
        profile: RetrievalProfile,
        workspace_id: Optional[str] = None,
        token_budget: int = 2000,
        seed_memory_id: Optional[str] = None,
    ):
        """Assemble a prompt-ready ContextPack for the given query and profile."""
        return await self.context_pack.build(
            query=query,
            profile=profile,
            workspace_id=workspace_id,
            token_budget=token_budget,
            seed_memory_id=seed_memory_id,
        )
