from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from app.config import settings
from app.architecture import generate_architecture_map

router = APIRouter(prefix="/architecture", tags=["architecture"])

class ScanRequest(BaseModel):
    project_name: str = None # Optional for backward compatibility, defaults to first project or ROOT

@router.post("/scan")
async def scan_architecture(req: ScanRequest):
    try:
        # Default to the first project in workspace if not specified
        root = settings.WORKSPACE_ROOT
        project_path = root
        
        if req.project_name:
            project_path = os.path.join(root, req.project_name)
            # Find recursively if not found directly
            if not os.path.exists(project_path) or not os.path.isdir(project_path):
                for root_dir, dirs, files in os.walk(root):
                    if req.project_name in dirs:
                        project_path = os.path.join(root_dir, req.project_name)
                        break
        else:
            # Pick first available project if none specified
            for item in os.listdir(root):
                p = os.path.join(root, item)
                if os.path.isdir(p) and not item.startswith("."):
                    project_path = p
                    break

        res = await generate_architecture_map(project_path)
        if res.get("status") == "error":
            raise Exception(res.get("message"))
            
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
