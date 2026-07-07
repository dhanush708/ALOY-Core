"""
memory/clustering.py
--------------------
SemanticClusterer: groups memories by embedding similarity using mini-batch k-means.

If scikit-learn is available it is used for proper k-means.
Otherwise a pure-Python Lloyd's algorithm fallback is used so that the
module never crashes at import time on minimal installs.
"""
import logging
import struct
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MemoryCluster:
    """A single cluster produced by SemanticClusterer."""
    centroid_memory_id: str          # Memory whose embedding is closest to centroid
    member_ids: List[str]            # All member memory IDs
    cohesion_score: float = 0.0      # Mean intra-cluster cosine similarity [0, 1]
    cluster_index: int = 0


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------

def _deserialize_f32(blob: bytes) -> List[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: List[float]) -> float:
    return math.sqrt(_dot(v, v))


def _cosine(a: List[float], b: List[float]) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


def _centroid(vecs: List[List[float]]) -> List[float]:
    if not vecs:
        return []
    n = len(vecs[0])
    c = [0.0] * n
    for v in vecs:
        for i in range(n):
            c[i] += v[i]
    total = len(vecs)
    return [x / total for x in c]


# ---------------------------------------------------------------------------
# Pure-Python Lloyd's k-means (fallback)
# ---------------------------------------------------------------------------

def _lloyd_kmeans(
    embeddings: List[List[float]],
    k: int,
    max_iter: int = 20,
) -> List[int]:
    """Return cluster assignments (list of ints, one per embedding)."""
    if k >= len(embeddings):
        return list(range(len(embeddings)))

    # Initialise: pick k evenly spaced vectors as centroids
    step = max(1, len(embeddings) // k)
    centroids = [embeddings[i * step] for i in range(k)]

    assignments = [0] * len(embeddings)
    for _ in range(max_iter):
        # Assignment step
        changed = False
        for idx, vec in enumerate(embeddings):
            best_k = max(range(k), key=lambda ki: _cosine(vec, centroids[ki]))
            if best_k != assignments[idx]:
                assignments[idx] = best_k
                changed = True

        # Update step
        cluster_vecs: List[List[List[float]]] = [[] for _ in range(k)]
        for idx, ki in enumerate(assignments):
            cluster_vecs[ki].append(embeddings[idx])

        for ki in range(k):
            if cluster_vecs[ki]:
                centroids[ki] = _centroid(cluster_vecs[ki])

        if not changed:
            break

    return assignments


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SemanticClusterer:
    """
    Cluster a set of memory IDs by their stored embedding vectors.

    Usage::
        clusterer = SemanticClusterer(db_pool)
        clusters  = await clusterer.cluster(memory_ids, n_clusters=5)
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def cluster(
        self,
        memory_ids: List[str],
        n_clusters: int = 5,
        max_iter: int = 25,
    ) -> List[MemoryCluster]:
        """
        Cluster *memory_ids* into at most *n_clusters* groups.

        Memories without stored embeddings are excluded silently.

        Returns:
            List of MemoryCluster objects, sorted by cluster_index.
        """
        if not memory_ids:
            return []

        # ----------------------------------------------------------------
        # 1. Load embeddings from DB
        # ----------------------------------------------------------------
        embeddings: List[Tuple[str, List[float]]] = []  # (memory_id, vector)

        placeholders = ",".join("?" * len(memory_ids))
        with self.db_pool.get_read_connection() as conn:
            # memories.rowid → memory_embeddings.rowid
            cursor = conn.execute(
                f"""
                SELECT m.id, me.embedding
                FROM   memories m
                JOIN   memory_embeddings me ON me.rowid = m.rowid
                WHERE  m.id IN ({placeholders})
                """,
                memory_ids,
            )
            for row in cursor.fetchall():
                try:
                    vec = _deserialize_f32(row["embedding"])
                    if vec:
                        embeddings.append((row["id"], vec))
                except Exception:
                    pass

        if not embeddings:
            logger.warning("SemanticClusterer: no embeddings found for provided memory IDs.")
            return []

        k = min(n_clusters, len(embeddings))
        ids   = [e[0] for e in embeddings]
        vecs  = [e[1] for e in embeddings]

        # ----------------------------------------------------------------
        # 2. Run k-means (sklearn preferred, Lloyd fallback)
        # ----------------------------------------------------------------
        try:
            from sklearn.cluster import MiniBatchKMeans  # type: ignore
            import numpy as np
            X = np.array(vecs, dtype=np.float32)
            km = MiniBatchKMeans(n_clusters=k, max_iter=max_iter, n_init=3, random_state=42)
            assignments = km.fit_predict(X).tolist()
        except ImportError:
            assignments = _lloyd_kmeans(vecs, k, max_iter)
        except Exception as e:
            logger.warning(f"SemanticClusterer sklearn error: {e}. Falling back to Lloyd's.")
            assignments = _lloyd_kmeans(vecs, k, max_iter)

        # ----------------------------------------------------------------
        # 3. Build MemoryCluster objects
        # ----------------------------------------------------------------
        from collections import defaultdict
        cluster_map: dict = defaultdict(list)  # cluster_idx → list of (memory_id, vec)
        for mem_id, vec, ki in zip(ids, vecs, assignments):
            cluster_map[ki].append((mem_id, vec))

        clusters: List[MemoryCluster] = []
        for ki, members in cluster_map.items():
            member_ids_k  = [m[0] for m in members]
            member_vecs_k = [m[1] for m in members]

            # Centroid of this cluster
            c = _centroid(member_vecs_k)

            # Find the memory whose embedding is closest to the centroid
            best_id = member_ids_k[0]
            best_sim = -1.0
            for mem_id, vec in members:
                sim = _cosine(vec, c)
                if sim > best_sim:
                    best_sim = sim
                    best_id = mem_id

            # Cohesion: mean pairwise cosine similarity
            cohesion = 0.0
            if len(member_vecs_k) > 1:
                sims = []
                for i in range(len(member_vecs_k)):
                    for j in range(i + 1, len(member_vecs_k)):
                        sims.append(_cosine(member_vecs_k[i], member_vecs_k[j]))
                cohesion = sum(sims) / len(sims) if sims else 0.0

            clusters.append(
                MemoryCluster(
                    centroid_memory_id=best_id,
                    member_ids=member_ids_k,
                    cohesion_score=round(cohesion, 4),
                    cluster_index=ki,
                )
            )

        clusters.sort(key=lambda c: c.cluster_index)
        return clusters

    async def find_near_duplicates(
        self,
        memory_ids: List[str],
        similarity_threshold: float = 0.95,
    ) -> List[Tuple[str, str, float]]:
        """
        Return pairs of memory IDs whose embeddings are above *similarity_threshold*.

        Returns list of (id_a, id_b, similarity) tuples.
        """
        placeholders = ",".join("?" * len(memory_ids))
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT m.id, me.embedding
                FROM   memories m
                JOIN   memory_embeddings me ON me.rowid = m.rowid
                WHERE  m.id IN ({placeholders})
                """,
                memory_ids,
            )
            rows = cursor.fetchall()

        pairs: List[Tuple[str, str, float]] = []
        items = []
        for row in rows:
            try:
                vec = _deserialize_f32(row["embedding"])
                if vec:
                    items.append((row["id"], vec))
            except Exception:
                pass

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                sim = _cosine(items[i][1], items[j][1])
                if sim >= similarity_threshold:
                    pairs.append((items[i][0], items[j][0], round(sim, 4)))

        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs
