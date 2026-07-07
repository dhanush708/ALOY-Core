"""
tests/test_memory/test_advanced_memory.py
-----------------------------------------
Tests for all Mission 9 Advanced Memory extensions:
  - TagManager
  - CollectionManager
  - ImportanceScorer.score_extended
  - MemoryLinker.get_neighbors / auto_link
  - MemoryCompressor
  - RetrievalProfileEngine
  - SemanticClusterer
  - ConsolidationScorer
  - AgentMemoryHooks
  - KnowledgeMemoryBridge
  - MemoryManager workspace APIs
"""
import pytest
import asyncio
import math
import struct
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Return a minimal mock db_pool for unit tests."""
    pool = MagicMock()
    # read_connection and write_connection are context managers
    pool.get_read_connection.return_value.__enter__ = MagicMock(return_value=MagicMock())
    pool.get_read_connection.return_value.__exit__ = MagicMock(return_value=False)
    pool.get_write_connection.return_value.__enter__ = MagicMock(return_value=MagicMock())
    pool.get_write_connection.return_value.__exit__ = MagicMock(return_value=False)
    return pool


def _encode_vec(v):
    return struct.pack(f"{len(v)}f", *v)


# ---------------------------------------------------------------------------
# 1. TagManager
# ---------------------------------------------------------------------------

class TestTagManager:
    def setup_method(self):
        """Use a real in-memory SQLite DB via the migration."""
        import sqlite3
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # Create minimal tables
        self.conn.execute("""
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                type TEXT, content TEXT, tier TEXT DEFAULT 'short_term',
                importance REAL DEFAULT 0.5, confidence REAL DEFAULT 0.5,
                archived_at TEXT, is_protected INTEGER DEFAULT 0
            )
        """)
        self.conn.execute("""
            CREATE TABLE memory_tags (
                memory_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (memory_id, tag)
            )
        """)
        self.conn.execute("CREATE INDEX idx_tags_tag ON memory_tags(tag)")
        # Insert two test memories
        self.conn.execute("INSERT INTO memories VALUES ('m1', 'fact', 'content1', 'short_term', 0.7, 0.8, NULL, 0)")
        self.conn.execute("INSERT INTO memories VALUES ('m2', 'code', 'content2', 'long_term', 0.5, 0.6, NULL, 0)")
        self.conn.commit()

        # Build a real pool wrapper
        pool = MagicMock()
        pool.get_read_connection.return_value.__enter__ = lambda s: self.conn
        pool.get_read_connection.return_value.__exit__ = MagicMock(return_value=False)
        pool.get_write_connection.return_value.__enter__ = lambda s: self.conn
        pool.get_write_connection.return_value.__exit__ = MagicMock(return_value=False)

        from memory.tags import TagManager
        self.tm = TagManager(pool)

    def test_add_and_get_tags(self):
        self.tm.add_tags("m1", ["python", "testing", "PYTHON"])  # dedup by normalisation
        tags = self.tm.get_tags("m1")
        assert "python" in tags
        assert "testing" in tags
        assert tags.count("python") == 1

    def test_remove_tags(self):
        self.tm.add_tags("m1", ["alpha", "beta"])
        self.tm.remove_tags("m1", ["alpha"])
        tags = self.tm.get_tags("m1")
        assert "alpha" not in tags
        assert "beta" in tags

    def test_find_by_tags_or(self):
        self.tm.add_tags("m1", ["x", "y"])
        self.tm.add_tags("m2", ["y", "z"])
        ids = self.tm.find_by_tags(["x"], require_all=False)
        assert "m1" in ids
        assert "m2" not in ids

    def test_find_by_tags_and(self):
        self.tm.add_tags("m1", ["a", "b"])
        self.tm.add_tags("m2", ["a"])
        # require_all=True: only m1 has BOTH a and b
        ids = self.tm.find_by_tags(["a", "b"], require_all=True)
        assert "m1" in ids
        assert "m2" not in ids

    def test_tag_overlap_jaccard(self):
        self.tm.add_tags("m1", ["p", "q", "r"])
        self.tm.add_tags("m2", ["q", "r", "s"])
        overlap = self.tm.get_tag_overlap("m1", "m2")
        # intersection={q,r} union={p,q,r,s} → 2/4 = 0.5
        assert abs(overlap - 0.5) < 0.01

    def test_empty_overlap(self):
        self.tm.add_tags("m1", ["only_m1"])
        overlap = self.tm.get_tag_overlap("m1", "m2")
        assert overlap == 0.0


# ---------------------------------------------------------------------------
# 2. CollectionManager
# ---------------------------------------------------------------------------

class TestCollectionManager:
    def setup_method(self):
        import sqlite3
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE memory_collections (
                id TEXT PRIMARY KEY, name TEXT, scope TEXT,
                scope_id TEXT, description TEXT, metadata TEXT, created_at TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE memory_collection_members (
                collection_id TEXT, memory_id TEXT, added_at TEXT,
                PRIMARY KEY (collection_id, memory_id)
            )
        """)
        self.conn.commit()

        pool = MagicMock()
        pool.get_read_connection.return_value.__enter__ = lambda s: self.conn
        pool.get_read_connection.return_value.__exit__ = MagicMock(return_value=False)
        pool.get_write_connection.return_value.__enter__ = lambda s: self.conn
        pool.get_write_connection.return_value.__exit__ = MagicMock(return_value=False)

        from memory.collections import CollectionManager
        self.cm = CollectionManager(pool)

    def test_create_and_get(self):
        col = self.cm.create("my-col", scope="workspace", scope_id="ws1")
        fetched = self.cm.get(col.id)
        assert fetched is not None
        assert fetched.name == "my-col"
        assert fetched.scope == "workspace"

    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError):
            self.cm.create("bad", scope="invalid_scope")

    def test_add_and_list_members(self):
        col = self.cm.create("members-test", scope="global")
        self.cm.add_memory(col.id, "mem-abc")
        self.cm.add_memory(col.id, "mem-def")
        self.cm.add_memory(col.id, "mem-abc")  # idempotent
        ids = self.cm.list_memory_ids(col.id)
        assert "mem-abc" in ids
        assert "mem-def" in ids
        assert ids.count("mem-abc") == 1

    def test_list_by_scope(self):
        self.cm.create("ws-col-1", scope="workspace", scope_id="ws42")
        self.cm.create("ws-col-2", scope="workspace", scope_id="ws42")
        self.cm.create("user-col", scope="user", scope_id="u1")
        ws_cols = self.cm.list_by_scope("workspace", scope_id="ws42")
        assert len(ws_cols) == 2

    def test_find_or_create_workspace_collection(self):
        col_a = self.cm.find_or_create_workspace_collection("ws99")
        col_b = self.cm.find_or_create_workspace_collection("ws99")
        assert col_a.id == col_b.id  # same collection returned

    def test_delete_collection(self):
        col = self.cm.create("to-delete", scope="global")
        assert self.cm.delete(col.id)
        assert self.cm.get(col.id) is None


# ---------------------------------------------------------------------------
# 3. ImportanceScorer.score_extended
# ---------------------------------------------------------------------------

class TestImportanceScorerExtended:
    def setup_method(self):
        from memory.importance import ImportanceScorer
        self.scorer = ImportanceScorer()

    def test_base_score_unchanged(self):
        """score() signature must not be broken."""
        s = self.scorer.score(0.5, 0, "", 0.0, 0.5, False)
        assert 0.0 <= s <= 1.0

    def test_extended_score_higher_with_agent_signal(self):
        base = self.scorer.score_extended(0.5, 0, "", agent_signal=0.0)
        boosted = self.scorer.score_extended(0.5, 0, "", agent_signal=1.0)
        assert boosted > base

    def test_extended_score_higher_with_knowledge_reuse(self):
        base = self.scorer.score_extended(0.5, 0, "")
        boosted = self.scorer.score_extended(0.5, 0, "", knowledge_reuse_count=50)
        assert boosted > base

    def test_extended_score_bounded(self):
        s = self.scorer.score_extended(
            1.0, 1000, "",
            user_explicit_boost=1.0,
            agent_signal=1.0,
            reasoning_depth=10,
            knowledge_reuse_count=100,
        )
        assert 0.0 <= s <= 1.0

    def test_reasoning_depth_log_scaled(self):
        s0 = self.scorer.score_extended(0.5, 0, "", reasoning_depth=0)
        s1 = self.scorer.score_extended(0.5, 0, "", reasoning_depth=1)
        s5 = self.scorer.score_extended(0.5, 0, "", reasoning_depth=5)
        assert s0 <= s1 <= s5


# ---------------------------------------------------------------------------
# 4. ConsolidationScorer
# ---------------------------------------------------------------------------

class TestConsolidationScorer:
    def setup_method(self):
        from memory.consolidation import ConsolidationScorer
        self.scorer = ConsolidationScorer()

    def _make_vec(self, val=0.5, dim=8):
        return [val] * dim

    def test_identical_embeddings_high_score(self):
        v = self._make_vec(0.7)
        score = self.scorer.score(v, v, 0.8, 0.8, 0.9, 0.9, None, None, 1.0, 0.5)
        assert score > 0.7

    def test_orthogonal_embeddings_lower_score(self):
        a = [1.0] + [0.0] * 7
        b = [0.0, 1.0] + [0.0] * 6
        score = self.scorer.score(a, b, 0.5, 0.5, 0.5, 0.5, None, None, 0.0, 0.0)
        assert score < 0.5

    def test_score_bounded(self):
        v = self._make_vec(0.5)
        score = self.scorer.score(v, v, 1.0, 1.0, 1.0, 1.0, None, None, 1.0, 1.0)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# 5. MemoryCompressor (unit)
# ---------------------------------------------------------------------------

class TestMemoryCompressor:
    def test_default_summarize_short(self):
        from memory.compression import _default_summarize
        content = "Short content."
        assert _default_summarize(content) == content

    def test_default_summarize_long(self):
        from memory.compression import _default_summarize
        content = "This is sentence one. This is sentence two. " * 20
        result = _default_summarize(content)
        assert len(result) < len(content)
        assert result.endswith(".")

    def test_default_summarize_truncates_at_200(self):
        from memory.compression import _default_summarize
        content = "x" * 500
        result = _default_summarize(content)
        assert len(result) <= 203  # 200 + ellipsis


# ---------------------------------------------------------------------------
# 6. SemanticClusterer — near-duplicate detection
# ---------------------------------------------------------------------------

class TestSemanticClusterer:
    def test_cosine_same_vector(self):
        from memory.clustering import _cosine
        v = [1.0, 0.5, 0.3]
        assert abs(_cosine(v, v) - 1.0) < 1e-6

    def test_cosine_orthogonal(self):
        from memory.clustering import _cosine
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine(a, b)) < 1e-6

    def test_centroid(self):
        from memory.clustering import _centroid
        vecs = [[1.0, 0.0], [0.0, 1.0]]
        c = _centroid(vecs)
        assert abs(c[0] - 0.5) < 1e-6
        assert abs(c[1] - 0.5) < 1e-6

    def test_lloyd_kmeans_basic(self):
        from memory.clustering import _lloyd_kmeans
        # Three clearly separated clusters
        vecs = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9], [0.5, 0.5]]
        assignments = _lloyd_kmeans(vecs, k=2)
        assert len(assignments) == 5
        # Items 0,1 should be in the same cluster; items 2,3 in another
        assert assignments[0] == assignments[1]
        assert assignments[2] == assignments[3]


# ---------------------------------------------------------------------------
# 7. RetrievalProfileEngine
# ---------------------------------------------------------------------------

class TestRetrievalProfileEngine:
    def test_all_profiles_have_config(self):
        from memory.profiles import RetrievalProfileEngine, RetrievalProfile, _PROFILE_CONFIGS
        for profile in RetrievalProfile:
            assert profile in _PROFILE_CONFIGS

    def test_profile_weights_sum_to_one(self):
        from memory.profiles import _PROFILE_CONFIGS
        for profile, cfg in _PROFILE_CONFIGS.items():
            total = cfg.w_semantic + cfg.w_importance + cfg.w_recency
            assert abs(total - 1.0) < 1e-6, f"{profile}: weights sum to {total}"

    @pytest.mark.asyncio
    async def test_retrieve_delegates_to_engine(self):
        from memory.profiles import RetrievalProfileEngine, RetrievalProfile
        from memory.types import ScoredMemory, Memory

        mock_engine = MagicMock()
        fake_mem = Memory(id="x1", type="fact", content="test content")
        fake_sm  = ScoredMemory(
            memory=fake_mem,
            score=0.8,
            relevance_details={"rrf": 0.8, "importance": 0.7, "recency": 0.6},
        )
        mock_engine.retrieve = AsyncMock(return_value=[fake_sm])

        engine = RetrievalProfileEngine(mock_engine, tag_manager=None)
        results = await engine.retrieve("test query", RetrievalProfile.CODING)
        assert len(results) >= 0  # Just ensure it runs without error
        mock_engine.retrieve.assert_called_once()


# ---------------------------------------------------------------------------
# 8. AgentMemoryHooks
# ---------------------------------------------------------------------------

class TestAgentMemoryHooks:
    @pytest.mark.asyncio
    async def test_record_success_stores_memory(self):
        from memory.agent_hooks import AgentMemoryHooks, TAG_SUCCESS

        mock_mem_mgr = MagicMock()
        fake_mem = MagicMock()
        fake_mem.id = "new-mem-id"
        mock_mem_mgr.store = AsyncMock(return_value=fake_mem)

        mock_tags = MagicMock()
        mock_cols = MagicMock()
        mock_cols.find_or_create_workspace_collection = MagicMock(return_value=MagicMock(id="col1"))

        hooks = AgentMemoryHooks(mock_mem_mgr, mock_tags, mock_cols)
        result_id = await hooks.record_success("Build project", "Succeeded", workspace_id="ws1")

        assert result_id == "new-mem-id"
        mock_mem_mgr.store.assert_called_once()
        mock_tags.add_tags.assert_called_once()
        tag_call_args = mock_tags.add_tags.call_args[0]
        assert TAG_SUCCESS in tag_call_args[1]

    @pytest.mark.asyncio
    async def test_record_failure_has_higher_importance(self):
        from memory.agent_hooks import AgentMemoryHooks

        call_args = {}

        async def fake_store(type, content, tier, importance, metadata, **kwargs):
            call_args['importance'] = importance
            m = MagicMock()
            m.id = "fail-id"
            return m

        mock_mem = MagicMock()
        mock_mem.store = fake_store
        mock_tags = MagicMock()
        mock_cols = MagicMock()
        mock_cols.find_or_create_workspace_collection = MagicMock(return_value=MagicMock(id="c"))

        hooks = AgentMemoryHooks(mock_mem, mock_tags, mock_cols)
        await hooks.record_failure("Some task", "Error msg")
        assert call_args.get('importance', 0) >= 0.7


# ---------------------------------------------------------------------------
# 9. KnowledgeMemoryBridge
# ---------------------------------------------------------------------------

class TestKnowledgeMemoryBridge:
    @pytest.mark.asyncio
    async def test_store_temporary_sets_expiry(self):
        from memory.knowledge_hooks import KnowledgeMemoryBridge, TAG_TEMP

        stored_kwargs = {}

        async def fake_store(type, content, tier, confidence, importance, source, expires_at, metadata):
            stored_kwargs['expires_at'] = expires_at
            stored_kwargs['tier'] = tier
            m = MagicMock()
            m.id = "tmp-id"
            m.confidence = confidence
            m.importance = importance
            return m

        mock_mem = MagicMock()
        mock_mem.store = fake_store
        mock_mem.db_pool = MagicMock()
        mock_tags = MagicMock()

        bridge = KnowledgeMemoryBridge(mock_mem, mock_tags)
        mid = await bridge.store_temporary("Fetched fact", ttl_hours=6)
        assert mid == "tmp-id"
        assert stored_kwargs['tier'] == "short_term"
        assert stored_kwargs['expires_at'] is not None

        # Verify tag applied
        mock_tags.add_tags.assert_called_once()
        applied_tags = mock_tags.add_tags.call_args[0][1]
        assert TAG_TEMP in applied_tags

    @pytest.mark.asyncio
    async def test_promote_to_permanent(self):
        from memory.knowledge_hooks import KnowledgeMemoryBridge, TAG_TEMP, TAG_VERIFIED

        fake_mem = MagicMock()
        fake_mem.confidence = 0.6
        fake_mem.importance = 0.5

        mock_mem = MagicMock()
        mock_mem.get = AsyncMock(return_value=fake_mem)
        mock_mem.update = AsyncMock(return_value=None)

        mock_tags = MagicMock()

        bridge = KnowledgeMemoryBridge(mock_mem, mock_tags)
        result = await bridge.promote_to_permanent("mid-123")
        assert result is True
        mock_mem.update.assert_called_once()
        update_kwargs = mock_mem.update.call_args[1] if mock_mem.update.call_args[1] else {}
        assert update_kwargs.get('tier') == 'long_term' or 'long_term' in str(mock_mem.update.call_args)


# ---------------------------------------------------------------------------
# 10. MemoryManager workspace APIs (smoke test)
# ---------------------------------------------------------------------------

class TestMemoryManagerWorkspaceAPI:
    @pytest.mark.asyncio
    async def test_store_workspace_memory_tags_with_workspace(self):
        """Smoke test: store_workspace_memory should attach a workspace tag."""
        from memory.manager import MemoryManager
        from memory.types import Memory

        fake_mem = Memory(id="ws-mem-1", type="fact", content="workspace content")

        with patch('memory.manager.MemoryStore') as MockStore, \
             patch('memory.manager.VectorStore'), \
             patch('memory.manager.EmbeddingEngine'), \
             patch('memory.manager.WorkingMemory'), \
             patch('memory.manager.ImportanceScorer') as MockScorer, \
             patch('memory.manager.DecayEngine'), \
             patch('memory.manager.RetrievalEngine'), \
             patch('memory.manager.MemoryLinker'), \
             patch('memory.manager.TagManager') as MockTags, \
             patch('memory.manager.CollectionManager') as MockCols, \
             patch('memory.manager.MemoryCompressor'), \
             patch('memory.manager.SemanticClusterer'), \
             patch('memory.manager.ConsolidationEngine'), \
             patch('memory.manager.RetrievalProfileEngine'), \
             patch('memory.manager.ContextPackBuilder'), \
             patch('memory.manager.AgentMemoryHooks'), \
             patch('memory.manager.KnowledgeMemoryBridge'):

            MockScorer.return_value.score.return_value = 0.7
            mock_store_instance = MockStore.return_value
            mock_store_instance.create = AsyncMock()
            MockTags.return_value.add_tags = MagicMock()
            mock_col_instance = MagicMock()
            mock_col_instance.id = "col-id"
            MockCols.return_value.find_or_create_workspace_collection.return_value = mock_col_instance
            MockCols.return_value.add_memory = MagicMock()

            pool = _make_mock_db()
            mgr = MemoryManager(pool)
            # Patch the store method directly to avoid full pipeline
            mgr.store = AsyncMock(return_value=fake_mem)

            mem = await mgr.store_workspace_memory("ws-test", "fact", "workspace content")
            assert mem.id == "ws-mem-1"
            mgr.tags.add_tags.assert_called_once()
            args = mgr.tags.add_tags.call_args[0]
            assert "workspace:ws-test" in args[1]
