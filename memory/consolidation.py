"""
memory/consolidation.py
-----------------------
ConsolidationEngine: idle-time background task that promotes, compresses,
deduplicates, and archives memories using multi-factor scoring.

ConsolidationScorer: produces a merge score from 6 signals:
  - cosine_similarity  (weight 0.35)
  - importance_delta   (weight 0.20)  — prefer merging lower-importance ones
  - confidence         (weight 0.15)
  - recency            (weight 0.15)
  - tag_overlap        (weight 0.10)
  - graph_link_weight  (weight 0.05)
"""
import json
import logging
import math
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Consolidation Scorer
# ---------------------------------------------------------------------------

class ConsolidationScorer:
    """
    Multi-factor score for deciding whether two memories should be merged.
    Higher score → stronger candidate for merge.
    """

    WEIGHTS = {
        "cosine_similarity": 0.35,
        "importance_delta":  0.20,
        "confidence":        0.15,
        "recency":           0.15,
        "tag_overlap":       0.10,
        "graph_link":        0.05,
    }

    @staticmethod
    def _deserialize(blob: bytes) -> List[float]:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na  = math.sqrt(sum(x * x for x in a))
        nb  = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    @staticmethod
    def _recency_score(last_accessed_at: Optional[str]) -> float:
        if not last_accessed_at:
            return 0.0
        try:
            t = datetime.fromisoformat(last_accessed_at)
            hours = (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
            return math.exp(-0.02 * max(0, hours))
        except Exception:
            return 0.0

    def score(
        self,
        emb_a: List[float],
        emb_b: List[float],
        importance_a: float,
        importance_b: float,
        confidence_a: float,
        confidence_b: float,
        last_accessed_a: Optional[str],
        last_accessed_b: Optional[str],
        tag_overlap: float = 0.0,
        graph_link_weight: float = 0.0,
    ) -> float:
        """
        Compute the multi-factor merge score for a pair of memories.
        Returns a float in [0, 1]. Higher = stronger merge candidate.
        """
        cos_sim     = self._cosine(emb_a, emb_b) if emb_a and emb_b else 0.0
        # Importance delta: memories closer in importance score → better merge
        imp_delta   = 1.0 - abs(importance_a - importance_b)
        # Confidence: use the mean; low-confidence pairs are better merge targets
        avg_conf    = (confidence_a + confidence_b) / 2.0
        # Recency: average recency (less recent → higher archival pressure)
        avg_recency = (
            self._recency_score(last_accessed_a) + self._recency_score(last_accessed_b)
        ) / 2.0

        total = (
            self.WEIGHTS["cosine_similarity"] * cos_sim     +
            self.WEIGHTS["importance_delta"]  * imp_delta   +
            self.WEIGHTS["confidence"]        * avg_conf    +
            self.WEIGHTS["recency"]           * avg_recency +
            self.WEIGHTS["tag_overlap"]       * tag_overlap +
            self.WEIGHTS["graph_link"]        * min(1.0, graph_link_weight)
        )
        return min(1.0, max(0.0, total))


# ---------------------------------------------------------------------------
# Consolidation Engine
# ---------------------------------------------------------------------------

class ConsolidationEngine:
    """
    Runs periodic idle-time consolidation over the memory store.

    Called from the kernel scheduler or directly via `consolidate()`.
    Logs every run to `mem_consolidation_log`.
    """

    def __init__(
        self,
        db_pool,
        compressor,
        tag_manager,
        clusterer,
        promotion_threshold: int = 5,        # access_count for short_term → long_term
        dedup_threshold: float = 0.80,        # merge score threshold
        archival_importance_threshold: float = 0.05,
    ):
        self.db_pool                  = db_pool
        self.compressor               = compressor
        self.tag_manager              = tag_manager
        self.clusterer                = clusterer
        self.scorer                   = ConsolidationScorer()
        self.promotion_threshold      = promotion_threshold
        self.dedup_threshold          = dedup_threshold
        self.archival_threshold       = archival_importance_threshold

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _get_embedding(self, conn, memory_rowid: int) -> List[float]:
        cursor = conn.execute(
            "SELECT embedding FROM memory_embeddings WHERE rowid = ?", (memory_rowid,)
        )
        row = cursor.fetchone()
        if row and row["embedding"]:
            n = len(row["embedding"]) // 4
            return list(struct.unpack(f"{n}f", row["embedding"]))
        return []

    # ------------------------------------------------------------------
    # Step 1: Promote high-access short_term → long_term
    # ------------------------------------------------------------------

    def _promote(self, conn) -> int:
        now = self._now()
        cursor = conn.execute(
            """
            SELECT id FROM memories
            WHERE  tier = 'short_term'
              AND  access_count >= ?
              AND  archived_at IS NULL
            """,
            (self.promotion_threshold,),
        )
        ids = [row["id"] for row in cursor.fetchall()]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE memories SET tier = 'long_term', updated_at = ? WHERE id IN ({placeholders})",
                [now] + ids,
            )
            logger.info(f"consolidation: promoted {len(ids)} memories to long_term.")
        return len(ids)

    # ------------------------------------------------------------------
    # Step 2: Compress then archive low-importance unprotected memories
    # ------------------------------------------------------------------

    async def _compress_archive(self) -> int:
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id FROM memories
                WHERE  importance <= ?
                  AND  archived_at IS NULL
                  AND  is_protected = 0
                  AND  tier != 'permanent'
                """,
                (self.archival_threshold,),
            )
            ids = [row["id"] for row in cursor.fetchall()]
        if not ids:
            return 0
        count = await self.compressor.compress_batch(ids)
        now = self._now()
        placeholders = ",".join("?" * len(ids))
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                f"UPDATE memories SET archived_at = ? WHERE id IN ({placeholders})",
                [now] + ids,
            )
        return count

    # ------------------------------------------------------------------
    # Step 3: Deduplicate via ConsolidationScorer
    # ------------------------------------------------------------------

    def _merge_pair(self, conn, keep_id: str, drop_id: str) -> None:
        """Merge drop_id into keep_id: append content, then archive drop_id."""
        cursor = conn.execute(
            "SELECT content, access_count FROM memories WHERE id = ?", (keep_id,)
        )
        keep_row = cursor.fetchone()
        cursor = conn.execute(
            "SELECT content FROM memories WHERE id = ?", (drop_id,)
        )
        drop_row = cursor.fetchone()

        if not keep_row or not drop_row:
            return

        merged_content = (
            keep_row["content"] + "\n\n[merged] " + drop_row["content"]
        )
        now = self._now()
        conn.execute(
            """
            UPDATE memories
            SET content      = ?,
                access_count = access_count + ?,
                updated_at   = ?,
                version      = version + 1
            WHERE id = ?
            """,
            (merged_content, keep_row["access_count"], now, keep_id),
        )
        conn.execute(
            "UPDATE memories SET archived_at = ?, updated_at = ? WHERE id = ?",
            (now, now, drop_id),
        )

    async def _dedup(self) -> int:
        """Fetch active memory IDs, cluster them, find near-duplicates, merge pairs."""
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                """
                SELECT m.id, m.rowid, m.importance, m.confidence, m.last_accessed_at
                FROM   memories m
                JOIN   memory_embeddings me ON me.rowid = m.rowid
                WHERE  m.archived_at IS NULL AND m.is_protected = 0
                LIMIT  500
                """
            )
            rows = cursor.fetchall()
        if len(rows) < 2:
            return 0

        ids = [r["id"] for r in rows]
        row_map = {r["id"]: r for r in rows}

        # Find near-duplicate pairs (async, runs outside write transaction)
        pairs = await self.clusterer.find_near_duplicates(ids, similarity_threshold=0.92)
        if not pairs:
            return 0

        merged = 0
        dropped: set = set()
        merges_to_perform = []

        for id_a, id_b, sim in pairs:
            if id_a in dropped or id_b in dropped:
                continue

            ra, rb = row_map[id_a], row_map[id_b]

            # Load embeddings (read-only)
            with self.db_pool.get_read_connection() as conn:
                emb_a = self._get_embedding(conn, ra["rowid"])
                emb_b = self._get_embedding(conn, rb["rowid"])

            tag_overlap = self.tag_manager.get_tag_overlap(id_a, id_b)

            merge_score = self.scorer.score(
                emb_a=emb_a, emb_b=emb_b,
                importance_a=ra["importance"], importance_b=rb["importance"],
                confidence_a=ra["confidence"], confidence_b=rb["confidence"],
                last_accessed_a=ra["last_accessed_at"],
                last_accessed_b=rb["last_accessed_at"],
                tag_overlap=tag_overlap,
            )

            if merge_score >= self.dedup_threshold:
                # Keep the more important memory
                keep, drop = (id_a, id_b) if ra["importance"] >= rb["importance"] else (id_b, id_a)
                dropped.add(drop)
                merges_to_perform.append((keep, drop))
                merged += 1

        # Perform database updates in a single serialized write transaction
        if merges_to_perform:
            with self.db_pool.get_write_connection() as conn:
                for keep, drop in merges_to_perform:
                    self._merge_pair(conn, keep, drop)
                    logger.debug(f"consolidation: merged {drop} -> {keep}")

        return merged

    # ------------------------------------------------------------------
    # Step 4: Semantic clustering (informational — stored in log)
    # ------------------------------------------------------------------

    async def _cluster(self) -> int:
        cursor_result = None
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                """
                SELECT m.id FROM memories m
                JOIN   memory_embeddings me ON me.rowid = m.rowid
                WHERE  m.archived_at IS NULL
                LIMIT  300
                """
            )
            ids = [row["id"] for row in cursor.fetchall()]

        if len(ids) < 2:
            return 0

        n_clusters = max(2, min(10, len(ids) // 10))
        clusters = await self.clusterer.cluster(ids, n_clusters=n_clusters)
        return len(clusters)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def consolidate(self) -> dict:
        """
        Run a full consolidation cycle.
        Returns a dict with counts and is logged to `mem_consolidation_log`.
        """
        t_start = time.monotonic()
        promoted = 0
        compressed = 0
        merged = 0
        archived_count = 0
        clusters_found = 0

        try:
            with self.db_pool.get_write_connection() as conn:
                promoted = self._promote(conn)

            compressed = await self._compress_archive()
            merged = await self._dedup()
            clusters_found = await self._cluster()

        except Exception as e:
            logger.error(f"ConsolidationEngine.consolidate() error: {e}", exc_info=True)

        duration_ms = int((time.monotonic() - t_start) * 1000)

        log_entry = {
            "id": str(uuid.uuid4()),
            "run_at": self._now(),
            "promoted": promoted,
            "compressed": compressed,
            "merged": merged,
            "archived": archived_count,
            "clusters_found": clusters_found,
            "duration_ms": duration_ms,
        }

        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO mem_consolidation_log
                        (id, run_at, promoted, compressed, merged, archived, clusters_found, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(log_entry.values()),
                )
        except Exception as e:
            logger.error(f"ConsolidationEngine: failed to write log: {e}")

        logger.info(
            f"Consolidation done in {duration_ms}ms: "
            f"promoted={promoted}, compressed={compressed}, merged={merged}, "
            f"clusters={clusters_found}"
        )
        return log_entry


# ---------------------------------------------------------------------------
# Async context manager shim for write connection
# ---------------------------------------------------------------------------

class _async_context:
    """Thin async wrapper around db_pool.get_write_connection() context manager."""

    def __init__(self, db_pool):
        self._pool = db_pool
        self._cm   = None
        self._conn = None

    async def __aenter__(self):
        self._cm   = self._pool.get_write_connection()
        self._conn = self._cm.__enter__()
        return self._conn

    async def __aexit__(self, *args):
        self._cm.__exit__(*args)
