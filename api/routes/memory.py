from fastapi import APIRouter, Request, Query, HTTPException
from typing import Optional, List

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/search")
async def search_memories(
    request: Request,
    query: str = Query("", description="Search query (leave empty to list recent)"),
    limit: int = Query(30, ge=1, le=100),
    tier: Optional[str] = None,
):
    """Search or list memories via hybrid FTS5 + vector retrieval."""
    memory_manager = getattr(request.app.state, "memory_manager", None)
    if not memory_manager:
        raise HTTPException(status_code=500, detail="Memory Manager not loaded")

    try:
        if query.strip():
            results = await memory_manager.retrieve(query=query, limit=limit)
        else:
            # Return recent memories from DB when no query
            with memory_manager.db_pool.get_read_connection() as conn:
                sql = """
                    SELECT id, type, tier, content, importance, confidence, access_count,
                           created_at, last_accessed_at
                    FROM memories
                    WHERE archived_at IS NULL
                """
                params = []
                if tier:
                    sql += " AND tier = ?"
                    params.append(tier)
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, params).fetchall()

            return [
                {
                    "id": r["id"],
                    "type": r["type"],
                    "tier": r["tier"],
                    "content": r["content"][:300] + ("..." if len(r["content"]) > 300 else ""),
                    "importance": round(r["importance"], 3),
                    "confidence": round(r["confidence"], 3),
                    "access_count": r["access_count"],
                    "created_at": r["created_at"],
                    "score": None,
                }
                for r in rows
            ]

        # Format scored results
        return [
            {
                "id": sm.memory.id,
                "type": sm.memory.type,
                "tier": sm.memory.tier,
                "content": sm.memory.content[:300] + ("..." if len(sm.memory.content) > 300 else ""),
                "importance": round(sm.memory.importance, 3),
                "confidence": round(sm.memory.confidence, 3),
                "access_count": sm.memory.access_count,
                "created_at": sm.memory.created_at,
                "score": round(sm.score, 4) if sm.score is not None else None,
            }
            for sm in results
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def memory_stats(request: Request):
    """Return memory tier counts and totals."""
    memory_manager = getattr(request.app.state, "memory_manager", None)
    if not memory_manager:
        raise HTTPException(status_code=500, detail="Memory Manager not loaded")

    try:
        with memory_manager.db_pool.get_read_connection() as conn:
            cursor = conn.execute("""
                SELECT tier, COUNT(*) as cnt
                FROM memories
                WHERE archived_at IS NULL
                GROUP BY tier
            """)
            rows = cursor.fetchall()

            total_cursor = conn.execute(
                "SELECT COUNT(*) as total FROM memories WHERE archived_at IS NULL"
            )
            total = total_cursor.fetchone()["total"]

        tiers = {r["tier"]: r["cnt"] for r in rows}
        return {
            "total": total,
            "short_term": tiers.get("short_term", 0),
            "long_term": tiers.get("long_term", 0),
            "permanent": tiers.get("permanent", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
