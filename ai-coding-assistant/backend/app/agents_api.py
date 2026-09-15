"""HTTP API for IDE-style agent capabilities and bounded repair."""
from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent_runtime import AgentContext, agent_registry
from app.capabilities import capability_summary
from app.repair_loop import RepairIssue, repair_issue
from app.project_paths import resolve_project_root
from app.verified_candidate_store import get_verified_repair, apply_verified_repair, rollback_applied_repair

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentRunRequest(BaseModel):
    agent: str
    task: str
    project_name: str = "default"
    files: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    extra_context: str = ""


class RepairRequest(BaseModel):
    task: str
    project_name: str = "default"
    files: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    validation_plan: List[Dict[str, Any]] = Field(default_factory=list)
    max_attempts: int | None = None


class ApplyVerifiedRepairRequest(BaseModel):
    confirm: bool = False


class RollbackVerifiedRepairRequest(BaseModel):
    confirm: bool = False
    reason: str = "Manual rollback requested"


@router.get("")
def list_agents():
    return {"agents": agent_registry.names(), "capabilities": capability_summary()}


@router.post("/run")
async def run_named_agent(req: AgentRunRequest):
    if req.agent not in agent_registry.names():
        raise HTTPException(status_code=404, detail=f"Unknown agent '{req.agent}'")
    try:
        project_root = str(resolve_project_root(req.project_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await agent_registry.run(req.agent, AgentContext(
        task=req.task,
        project_name=req.project_name,
        project_root=project_root,
        files=req.files,
        evidence=req.evidence,
        extra_context=req.extra_context,
    ))
    return result.to_dict()


@router.post("/repair")
async def run_repair(req: RepairRequest):
    try:
        issue = RepairIssue(
            task=req.task,
            project_name=req.project_name,
            files=req.files,
            evidence=req.evidence,
            validation_plan=req.validation_plan,
        )
        return await repair_issue(issue, req.max_attempts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/repairs/{issue_id}")
def get_repair_candidate(issue_id: str):
    candidate = get_verified_repair(issue_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Verified repair not found")
    return candidate


@router.post("/repairs/{issue_id}/apply")
def apply_repair_candidate(issue_id: str, req: ApplyVerifiedRepairRequest):
    try:
        return apply_verified_repair(issue_id, confirm=req.confirm)
    except KeyError:
        raise HTTPException(status_code=404, detail="Verified repair not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/repairs/{issue_id}/rollback")
def rollback_repair_candidate(issue_id: str, req: RollbackVerifiedRepairRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to rollback an applied repair")
    try:
        return rollback_applied_repair(issue_id, reason=req.reason)
    except KeyError:
        raise HTTPException(status_code=404, detail="Verified repair not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
