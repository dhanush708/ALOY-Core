from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path

doc_router = APIRouter(prefix="/api/docs", tags=["documentation"])
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

class IndexRequest(BaseModel):
    dir_path: str
    package: str
    version: str
    doc_type: Optional[str] = "api_reference"

# ------------------------------------------------------------------
# Documentation Subsystem Router (doc_router)
# ------------------------------------------------------------------

@doc_router.get("/search")
async def search_docs(
    request: Request,
    query: str,
    package: str,
    workspace_path: Optional[str] = None,
    doc_type: Optional[str] = None,
    limit: int = Query(5, ge=1, le=20)
):
    doc_intel = getattr(request.app.state, "doc_intelligence", None)
    if not doc_intel:
        raise HTTPException(status_code=500, detail="Documentation Intelligence not loaded")
        
    try:
        results = await doc_intel.search_docs(
            query=query,
            package=package,
            workspace_path=workspace_path,
            doc_type=doc_type,
            limit=limit
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@doc_router.get("/summarize")
async def summarize_docs(
    request: Request,
    query: str,
    package: str,
    workspace_path: Optional[str] = None
):
    doc_intel = getattr(request.app.state, "doc_intelligence", None)
    if not doc_intel:
        raise HTTPException(status_code=500, detail="Documentation Intelligence not loaded")
        
    try:
        result = await doc_intel.get_summary_and_examples(
            query=query,
            package=package,
            workspace_path=workspace_path
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@doc_router.post("/index")
async def index_docs(request: Request, payload: IndexRequest):
    doc_intel = getattr(request.app.state, "doc_intelligence", None)
    if not doc_intel:
        raise HTTPException(status_code=500, detail="Documentation Intelligence not loaded")
        
    dir_path = Path(payload.dir_path)
    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory path does not exist: {payload.dir_path}")
        
    try:
        count = await doc_intel.indexer.index_directory(
            dir_path=dir_path,
            package=payload.package,
            version=payload.version,
            doc_type=payload.doc_type
        )
        return {"status": "success", "indexed_chunks": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@doc_router.get("/packages")
async def list_packages(request: Request):
    db_pool = request.app.state.db_pool
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database pool not available")
        
    try:
        packages = []
        with db_pool.get_read_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT 
                       json_extract(metadata, '$.package') as package,
                       json_extract(metadata, '$.version') as version,
                       json_extract(metadata, '$.doc_type') as doc_type
                FROM memories 
                WHERE type = 'documentation'
            """)
            rows = cursor.fetchall()
            
        for r in rows:
            if r["package"]:
                packages.append({
                    "package": r["package"],
                    "version": r["version"] or "unknown",
                    "doc_type": r["doc_type"] or "api_reference"
                })
        return packages
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------------
# Knowledge Router (router)
# ------------------------------------------------------------------

@router.get("/query")
async def query_knowledge(
    request: Request,
    query: str,
    workspace_path: Optional[str] = None,
    package: Optional[str] = None
):
    router_engine = getattr(request.app.state, "knowledge_router", None)
    if not router_engine:
        raise HTTPException(status_code=500, detail="Knowledge Router not loaded")
        
    try:
        result = await router_engine.query_escalation(
            query=query,
            workspace_path=workspace_path,
            package=package
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/consolidate")
async def consolidate_research(request: Request):
    router_engine = getattr(request.app.state, "knowledge_router", None)
    if not router_engine:
        raise HTTPException(status_code=500, detail="Knowledge Router not loaded")
        
    try:
        count = await router_engine.consolidate_research()
        return {"status": "success", "consolidated_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cache/stats")
async def cache_stats(request: Request):
    router_engine = getattr(request.app.state, "knowledge_router", None)
    if not router_engine:
        raise HTTPException(status_code=500, detail="Knowledge Router not loaded")
        
    try:
        size = router_engine.cache.get_size()
        return {"cache_size": size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
