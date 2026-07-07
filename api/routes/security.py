from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

router = APIRouter(prefix="/api/security", tags=["security"])

class RestoreRequest(BaseModel):
    backup_path: str

class ProtectMemoryRequest(BaseModel):
    memory_id: str
    is_protected: bool

class SurgicalRollbackRequest(BaseModel):
    session_id: str
    checkpoint_id: str
    file_path: str

def get_backup_manager(request: Request):
    if not hasattr(request.app.state, "backup_manager"):
        raise HTTPException(status_code=500, detail="DatabaseBackupManager not initialized.")
    return request.app.state.backup_manager

def get_rollback_engine(request: Request):
    if not hasattr(request.app.state, "rollback_engine"):
        raise HTTPException(status_code=500, detail="AdvancedRollbackEngine not initialized.")
    return request.app.state.rollback_engine

def get_memory_manager(request: Request):
    if not hasattr(request.app.state, "memory_manager"):
        raise HTTPException(status_code=500, detail="MemoryManager not initialized.")
    return request.app.state.memory_manager

@router.post("/backup")
async def trigger_backup(request: Request):
    """Triggers an immediate database backup and executes GFS rotation."""
    mgr = get_backup_manager(request)
    try:
        backup_path = mgr.create_backup()
        return {"status": "success", "backup_path": backup_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/backups")
async def list_backups(request: Request):
    """Lists all daily, weekly, and monthly database backups."""
    mgr = get_backup_manager(request)
    try:
        backups = mgr.list_backups()
        return backups
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/backup/restore")
async def restore_backup(request: Request, body: RestoreRequest):
    """Restores the live database state from the specified backup path."""
    mgr = get_backup_manager(request)
    try:
        mgr.restore_backup(body.backup_path)
        return {"status": "success", "message": "Database restored successfully."}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/protect")
async def protect_memory(request: Request, body: ProtectMemoryRequest):
    """Locks or unlocks a memory to prevent automatic decay and consolidation deletion."""
    mgr = get_memory_manager(request)
    try:
        success = await mgr.protect_memory(body.memory_id, body.is_protected)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update memory protection.")
        return {"status": "success", "memory_id": body.memory_id, "is_protected": body.is_protected}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rollback/file")
async def revert_file(request: Request, body: SurgicalRollbackRequest):
    """Surgically rolls back a single file to its state at the specified checkpoint."""
    engine = get_rollback_engine(request)
    try:
        success = await engine.revert_single_file(body.session_id, body.checkpoint_id, body.file_path)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to revert target file surgically.")
        return {"status": "success", "message": f"Surgically reverted '{body.file_path}'."}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
