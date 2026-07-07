from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
from identity.metadata import CREATOR_METADATA

router = APIRouter(prefix="/api/profile", tags=["profile"])

@router.get("/metadata")
async def get_metadata():
    """Retrieve centralized creator and application metadata."""
    return CREATOR_METADATA

class ProfileData(BaseModel):
    name: str
    preferred_name: str
    age: int
    country: str
    preferences: str

@router.get("/status")
async def get_profile_status(request: Request):
    """Check if the user is onboarded."""
    identity_engine = getattr(request.app.state, "identity_engine", None)
    if not identity_engine:
        raise HTTPException(status_code=500, detail="Identity Engine not loaded")
    
    try:
        onboarded = await identity_engine.user_profile_exists()
        return {"onboarded": onboarded}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
async def get_profile(request: Request):
    """Retrieve user profile details."""
    identity_engine = getattr(request.app.state, "identity_engine", None)
    if not identity_engine:
        raise HTTPException(status_code=500, detail="Identity Engine not loaded")

    try:
        profile = await identity_engine.get_user_profile()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found. Complete onboarding to create one.")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile retrieval error: {str(e)}")

@router.post("")
async def save_profile(request: Request, data: ProfileData):
    """Create or update user profile."""
    identity_engine = getattr(request.app.state, "identity_engine", None)
    if not identity_engine:
        raise HTTPException(status_code=500, detail="Identity Engine not loaded")
    
    try:
        await identity_engine.save_user_profile(
            name=data.name,
            preferred_name=data.preferred_name,
            age=data.age,
            country=data.country,
            preferences=data.preferences
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reset")
async def reset_profile(request: Request):
    """Reset profile and wipe database memories/sessions."""
    identity_engine = getattr(request.app.state, "identity_engine", None)
    if not identity_engine:
        raise HTTPException(status_code=500, detail="Identity Engine not loaded")
    
    try:
        await identity_engine.reset_all()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("")
async def delete_profile(request: Request):
    """Delete user profile memory."""
    identity_engine = getattr(request.app.state, "identity_engine", None)
    if not identity_engine:
        raise HTTPException(status_code=500, detail="Identity Engine not loaded")
    
    try:
        await identity_engine.delete_user_profile()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export")
async def export_profile(request: Request):
    """Export profile settings as a JSON response file."""
    identity_engine = getattr(request.app.state, "identity_engine", None)
    if not identity_engine:
        raise HTTPException(status_code=500, detail="Identity Engine not loaded")
    
    try:
        profile = await identity_engine.get_user_profile()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        # Directly download settings as a JSON file attachment
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=profile,
            headers={"Content-Disposition": "attachment; filename=aloy_settings.json"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def import_profile(request: Request, data: ProfileData):
    """Import user profile details."""
    identity_engine = getattr(request.app.state, "identity_engine", None)
    if not identity_engine:
        raise HTTPException(status_code=500, detail="Identity Engine not loaded")
    
    try:
        await identity_engine.save_user_profile(
            name=data.name,
            preferred_name=data.preferred_name,
            age=data.age,
            country=data.country,
            preferences=data.preferences
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
