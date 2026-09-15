from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

class ModelSettingUpdate(BaseModel):
    model_name: str

class ModelPullRequest(BaseModel):
    model_name: str

class ModelDeleteRequest(BaseModel):
    model_name: str
    confirm: Optional[bool] = False
    force: Optional[bool] = False

# Simple in-memory role mapping fallback
# In a real scenario, this could be stored in SQLite settings table
ROLE_SETTINGS = {
    "planner": {"model_name": "llama3.1:latest", "source": "ollama"},
    "coder": {"model_name": "qwen2.5-coder:7b", "source": "ollama"},
    "reviewer": {"model_name": "llama3.1:latest", "source": "ollama"},
    "chat": {"model_name": getattr(settings, "DEFAULT_MODEL", "llama3.1:latest"), "source": "ollama"},
    "embedding": {"model_name": "nomic-embed-text:latest", "source": "ollama"}
}

def get_ollama_url():
    return getattr(settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip('/')

@router.get("/ollama")
async def get_ollama_status():
    url = f"{get_ollama_url()}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name"),
                    "size": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                    "details": m.get("details", {})
                })
            return {"status": "ok", "models": models}
    except Exception as e:
        logger.error(f"Failed to fetch Ollama status: {e}")
        return {"status": "offline", "error": str(e), "models": []}

@router.get("/settings")
async def get_model_settings():
    settings_list = [{"role": k, **v} for k, v in ROLE_SETTINGS.items()]
    return {"settings": settings_list}

@router.put("/settings/{role}")
async def set_model_setting(role: str, update: ModelSettingUpdate, validate: bool = True):
    if role not in ROLE_SETTINGS:
        ROLE_SETTINGS[role] = {}
    ROLE_SETTINGS[role]["model_name"] = update.model_name
    ROLE_SETTINGS[role]["source"] = "ollama" if ":" in update.model_name or "llama" in update.model_name else "api"
    
    if role == "chat":
        settings.chat_model = update.model_name
        settings.DEFAULT_MODEL = update.model_name
    
    return {"status": "ok", "role": role, "model_name": update.model_name}

@router.delete("/settings/{role}")
async def reset_model_setting(role: str):
    if role in ROLE_SETTINGS:
        default_model = "llama3.1:latest"
        ROLE_SETTINGS[role]["model_name"] = default_model
        if role == "chat":
            settings.chat_model = default_model
            settings.DEFAULT_MODEL = default_model
    return {"status": "ok"}

@router.get("/recommended")
async def get_recommended_models():
    return {"recommended": [
        {"name": "llama3.1:latest", "description": "Good all-around model", "role": "chat"},
        {"name": "qwen2.5-coder:7b", "description": "Excellent for coding", "role": "coder"},
        {"name": "nomic-embed-text:latest", "description": "Great for embeddings", "role": "embedding"}
    ]}

@router.post("/pull")
async def pull_ollama_model(req: ModelPullRequest):
    url = f"{get_ollama_url()}/api/pull"
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, json={"name": req.model_name, "stream": False})
            response.raise_for_status()
            return {"status": "pulled", "model": req.model_name}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/delete/preview")
async def delete_preview(req: ModelDeleteRequest):
    return {
        "status": "ok", 
        "model_name": req.model_name, 
        "message": f"Are you sure you want to delete {req.model_name}?"
    }

@router.post("/delete")
async def delete_ollama_model(req: ModelDeleteRequest):
    if not req.confirm:
        return {"status": "error", "message": "Deletion not confirmed."}
    
    url = f"{get_ollama_url()}/api/delete"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request("DELETE", url, json={"name": req.model_name})
            response.raise_for_status()
            return {"status": "deleted", "model": req.model_name}
    except Exception as e:
        return {"status": "error", "message": str(e)}
