from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from app.impact_analysis import analyze_impact

router = APIRouter(prefix="/impact", tags=["impact"])

class AnalyzeRequest(BaseModel):
    task: str
    file_paths: List[str]

@router.post("/analyze")
async def run_impact_analysis(req: AnalyzeRequest):
    try:
        # We just pick the first file as the target for the impact analysis script
        target_file = req.file_paths[0] if req.file_paths else "unknown"
        
        res = await analyze_impact(target_file, req.task)
        if res.get("status") == "error":
            raise Exception(res.get("message"))
            
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports")
async def get_impact_history():
    # Return empty history for now to satisfy frontend requirements
    return {"reports": []}
