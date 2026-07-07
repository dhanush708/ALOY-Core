from fastapi import APIRouter, Request, HTTPException, Query
from typing import List, Optional, Dict, Any

from evolution.proposal import ImprovementProposal

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.post("/scan", response_model=List[Dict[str, Any]])
async def run_evolution_scan(request: Request):
    """Trigger a self-improvement evolution scan and return drafted proposals."""
    engine = getattr(request.app.state, "evolution_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Evolution Engine is not available.")
    
    try:
        proposals = await engine.run_scan()
        return [p.to_dict() for p in proposals]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evolution scan failed: {str(e)}")


@router.get("/proposals", response_model=List[Dict[str, Any]])
async def get_evolution_proposals(
    request: Request,
    status: Optional[str] = Query(None, description="Filter proposals by status (e.g. pending, approved, rejected, applied)")
):
    """Get all self-improvement proposals, optionally filtered by status."""
    engine = getattr(request.app.state, "evolution_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Evolution Engine is not available.")
    
    proposals = await engine.get_proposals(status)
    return [p.to_dict() for p in proposals]


@router.post("/proposals/{proposal_id}/approve")
async def approve_evolution_proposal(proposal_id: str, request: Request):
    """Approve and apply a self-improvement proposal."""
    engine = getattr(request.app.state, "evolution_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Evolution Engine is not available.")
    
    success = await engine.approve(proposal_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to apply the proposal.")
    return {"status": "applied", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/reject")
async def reject_evolution_proposal(proposal_id: str, request: Request):
    """Reject a self-improvement proposal."""
    engine = getattr(request.app.state, "evolution_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Evolution Engine is not available.")
    
    success = await engine.reject(proposal_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to reject the proposal.")
    return {"status": "rejected", "proposal_id": proposal_id}
