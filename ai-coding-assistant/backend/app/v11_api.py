"""v1.1 intelligence, learning and evaluation API."""
from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.adaptive_orchestration import route_task
from app.experience_memory import search_experiences
from app.project_paths import resolve_project_root
from app.repository_intelligence import rank_relevant_files
from app.v11_evaluation import compare_benchmark_versions, list_benchmark_runs, record_benchmark_run, repair_efficiency_summary
from app.model_usage import model_usage_summary

router = APIRouter(prefix="/v1.1", tags=["v1.1 intelligence"])


class RoutePreviewRequest(BaseModel):
    task: str
    files: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)


class RepositoryContextRequest(BaseModel):
    project_name: str = "default"
    task: str
    files: List[str] = Field(default_factory=list)
    limit: int = 8


class ExperienceSearchRequest(BaseModel):
    project_name: str = "default"
    task: str
    files: List[str] = Field(default_factory=list)
    limit: int = 5


class BenchmarkRunRequest(BaseModel):
    version: str = "1.1.0"
    suite_name: str
    cases: List[Dict[str, Any]]


@router.get("/capabilities")
def capabilities():
    return {
        "version": "1.1.0",
        "adaptive_agent_routing": True,
        "repository_graph_context": True,
        "contextual_experience_memory": True,
        "benchmark_tracking": True,
        "production_outcome_learning": True,
        "model_weight_retraining": False,
        "safety_boundaries_preserved": True,
    }


@router.post("/routing/preview")
def routing_preview(req: RoutePreviewRequest):
    return route_task(req.task, files=req.files, evidence=req.evidence).to_dict()


@router.post("/repository/context")
def repository_context(req: RepositoryContextRequest):
    try:
        root = resolve_project_root(req.project_name)
        return rank_relevant_files(root, req.task, seed_files=req.files, limit=req.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/experiences/search")
def experiences_search(req: ExperienceSearchRequest):
    return {"experiences": search_experiences(project_name=req.project_name, task=req.task, files=req.files, limit=req.limit)}


@router.get("/evaluation/repair-efficiency")
def repair_efficiency(project_name: str | None = None, limit: int = 500):
    return repair_efficiency_summary(project_name, limit=limit)


@router.post("/evaluation/benchmarks")
def create_benchmark(req: BenchmarkRunRequest):
    try:
        return record_benchmark_run(version=req.version, suite_name=req.suite_name, cases=req.cases)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/evaluation/benchmarks")
def benchmarks(suite_name: str | None = None, limit: int = 50):
    return {"runs": list_benchmark_runs(suite_name=suite_name, limit=limit)}


@router.get("/evaluation/model-usage")
def model_usage(limit: int = 1000):
    return model_usage_summary(limit=limit)


@router.get("/evaluation/compare")
def compare_benchmarks(suite_name: str, baseline_version: str, candidate_version: str):
    try:
        return compare_benchmark_versions(
            suite_name=suite_name, baseline_version=baseline_version, candidate_version=candidate_version
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
