from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from pathlib import Path

from project.discovery import ProjectDiscovery
from project.tree import DirectoryTreeBuilder
from project.manifest import ManifestLoader

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    name: str
    root_path: str
    description: Optional[str] = ""
    metadata: Optional[Dict[str, Any]] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    root_path: str
    manifest_path: Optional[str] = None
    created_at: str
    updated_at: str
    metadata: Dict[str, Any]


class SessionStartRequest(BaseModel):
    metadata: Optional[Dict[str, Any]] = None


class SessionEndRequest(BaseModel):
    summary: Optional[str] = ""
    metadata: Optional[Dict[str, Any]] = None


class SessionResponse(BaseModel):
    id: str
    project_id: str
    started_at: str
    ended_at: Optional[str] = None
    summary: str
    metadata: Dict[str, Any]


class ProjectDetectRequest(BaseModel):
    path: str


def get_manager(request: Request):
    return request.app.state.project_manager


@router.get("", response_model=List[ProjectResponse])
async def list_projects(request: Request):
    """List all registered projects."""
    mgr = get_manager(request)
    return mgr.list_projects()


@router.post("", response_model=ProjectResponse)
async def create_project(request: Request, payload: ProjectCreateRequest):
    """Register a new project."""
    mgr = get_manager(request)
    try:
        project = mgr.create_project(
            name=payload.name,
            root_path=payload.root_path,
            description=payload.description,
            metadata=payload.metadata
        )
        return project
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, request: Request):
    """Get project details."""
    mgr = get_manager(request)
    project = mgr.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: str, request: Request):
    """Delete a registered project."""
    mgr = get_manager(request)
    deleted = mgr.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}


@router.post("/detect")
async def detect_project(payload: ProjectDetectRequest):
    """Detect nearest project root from a given path."""
    root = ProjectDiscovery.find_project_root(payload.path)
    if not root:
        raise HTTPException(status_code=404, detail="No project root detected")
    return {"project_root": root.as_posix()}


@router.get("/{project_id}/tree")
async def get_project_tree(project_id: str, request: Request, format: str = "nested"):
    """Get directory tree for the project."""
    mgr = get_manager(request)
    project = mgr.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    root_path = Path(project["root_path"])
    manifest_data = ManifestLoader.load(root_path)
    exclude_patterns = manifest_data["project"]["exclude_patterns"]

    try:
        if format == "text":
            tree_dict = DirectoryTreeBuilder.build(root_path, exclude_patterns)
            tree_str = DirectoryTreeBuilder.to_string(tree_dict)
            return {"tree": tree_str}
        else:
            tree_dict = DirectoryTreeBuilder.build(root_path, exclude_patterns)
            return tree_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build directory tree: {e}")


@router.post("/{project_id}/scan")
async def scan_project(project_id: str, request: Request):
    """Re-index all files inside the project root."""
    mgr = get_manager(request)
    try:
        stats = mgr.index_project_files(project_id)
        return {"status": "ok", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{project_id}/sessions", response_model=SessionResponse)
async def start_session(project_id: str, request: Request, payload: Optional[SessionStartRequest] = None):
    """Start a project session."""
    mgr = get_manager(request)
    meta = payload.metadata if payload else None
    try:
        session = mgr.start_session(project_id, meta)
        return session.to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{project_id}/sessions/{session_id}/end", response_model=SessionResponse)
async def end_session(project_id: str, session_id: str, request: Request, payload: Optional[SessionEndRequest] = None):
    """End a project session."""
    mgr = get_manager(request)
    summary = payload.summary if payload else ""
    meta = payload.metadata if payload else None
    try:
        session = mgr.end_session(session_id, summary, meta)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}/sessions", response_model=List[SessionResponse])
async def list_sessions(project_id: str, request: Request):
    """List sessions of a project."""
    mgr = get_manager(request)
    # Check if project exists
    project = mgr.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    sessions = mgr.list_sessions(project_id)
    return [s.to_dict() for s in sessions]
