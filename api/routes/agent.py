from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

router = APIRouter(prefix="/api/agent", tags=["agent"])


class SessionCreateRequest(BaseModel):
    goal: str
    project_id: Optional[str] = None



class SessionCreateResponse(BaseModel):
    session_id: str


class CheckpointRollbackRequest(BaseModel):
    checkpoint_id: str


def get_runtime(request: Request):
    if not hasattr(request.app.state, "agent_runtime"):
        raise HTTPException(status_code=500, detail="AgentRuntime not initialized.")
    return request.app.state.agent_runtime


@router.get("/sessions")
async def list_sessions(request: Request):
    """Lists all agent sessions."""
    runtime = get_runtime(request)
    try:
        with runtime.db_pool.get_read_connection() as conn:
            rows = conn.execute(
                "SELECT id, project_id, goal, status, created_at, updated_at FROM agent_sessions ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "session_id": r[0],
                "project_id": r[1],
                "goal": r[2],
                "status": r[3],
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session", response_model=SessionCreateResponse)
async def create_session(request: Request, body: SessionCreateRequest):
    """Starts a new agent session (goal + project_id)."""
    runtime = get_runtime(request)
    try:
        session_id = await runtime.start_session(body.goal, body.project_id)
        return {"session_id": session_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session_status(request: Request, session_id: str):
    """Gets details, task progress and checkpoints for a session."""
    runtime = get_runtime(request)
    status = await runtime.get_session_status(session_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return status


@router.post("/session/{session_id}/execute")
async def execute_session(request: Request, session_id: str):
    """Triggers background execution of the agent session."""
    runtime = get_runtime(request)
    try:
        await runtime.execute_session(session_id)
        return {"status": "execution_started"}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/pause")
async def pause_session(request: Request, session_id: str):
    """Pauses an executing session."""
    runtime = get_runtime(request)
    try:
        await runtime.pause_session(session_id)
        return {"status": "paused"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/resume")
async def resume_session(request: Request, session_id: str):
    """Resumes a paused session."""
    runtime = get_runtime(request)
    try:
        await runtime.resume_session(session_id)
        return {"status": "resumed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CheckpointResumeRequest(BaseModel):
    checkpoint_id: str


@router.post("/session/{session_id}/resume-from-checkpoint")
async def resume_session_from_checkpoint(request: Request, session_id: str, body: CheckpointResumeRequest):
    """Resumes executing the session starting from a specific checkpoint."""
    runtime = get_runtime(request)
    try:
        await runtime.resume_session_from_checkpoint(session_id, body.checkpoint_id)
        return {"status": "resume_started"}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/rollback")
async def rollback_session(request: Request, session_id: str, body: CheckpointRollbackRequest):
    """Rolls back the workspace to a specific checkpoint state."""
    runtime = get_runtime(request)
    try:
        await runtime.rollback_session(session_id, body.checkpoint_id)
        return {"status": "rolled_back"}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/tasks")
async def list_tasks(request: Request, session_id: str):
    """Lists all tasks with details and status for a session."""
    runtime = get_runtime(request)
    try:
        tasks = await runtime.task_queue.list_tasks(session_id)
        return [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "assigned_agent": t.assigned_agent,
                "priority": t.priority,
                "status": t.status.value,
                "depends_on": t.depends_on,
                "result": t.result,
                "error": t.error,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tasks
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
