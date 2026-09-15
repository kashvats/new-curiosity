"""FastAPI surface for Part 12 candidate-to-staging release orchestration."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.improvement_release_orchestrator import (
    cleanup_expired_release_workspaces, create_or_register_preview, create_release_from_verified,
    ingest_vulnerability_report, promote_staging_ready, reject_release, release_capabilities,
    run_release_pipeline,
)
from app.improvement_release_store import get_release_candidate, list_release_candidates, release_evidence
from app.improvement_scheduler_security import record_operator_audit, verify_operator
from app.project_paths import resolve_project_root

router = APIRouter(prefix="/improvements/releases", tags=["improvement-release"])


class ReleaseCreateRequest(BaseModel):
    project_name: str = "default"
    issue_id: str = Field(min_length=1, max_length=200)
    commit_sha: str | None = Field(default=None, max_length=160)
    scm_provider: str | None = Field(default=None, pattern="^(github|gitlab)$")
    scm_target: str | None = Field(default=None, max_length=300)
    require_preview: bool = False


class PreviewRequest(BaseModel):
    provider: str = Field(default="external", pattern="^(none|external)$")
    preview_url: str | None = Field(default=None, max_length=2000)


class StagingPromotionRequest(BaseModel):
    confirm: bool = False


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CleanupRequest(BaseModel):
    confirm: bool = False


def _operator(operator_id: str | None, operator_token: str | None) -> dict[str, Any]:
    try:
        return verify_operator(operator_id, operator_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


def _audit(operator: dict[str, Any], action: str, *, project_name: str | None = None, release_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    record_operator_audit(operator=operator, action=action, project_name=project_name, schedule_id=None,
                          metadata={"release_id": release_id, **(metadata or {})})


def _validate_project(project_name: str) -> None:
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _public_release(item: dict[str, Any]) -> dict[str, Any]:
    public = dict(item)
    public["workspace_prepared"] = bool(public.pop("workspace_path", None))
    return public


def _public_preview(item: dict[str, Any]) -> dict[str, Any]:
    public = dict(item)
    metadata = dict(public.get("metadata") or {})
    metadata.pop("workspace_path", None)
    public["metadata"] = metadata
    return public


def _public_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    public = dict(payload)
    if isinstance(public.get("release"), dict):
        public["release"] = _public_release(public["release"])
    public["artifacts"] = [{k: v for k, v in item.items() if k != "path"} for item in public.get("artifacts", [])]
    public["previews"] = [_public_preview(item) for item in public.get("previews", [])]
    return public


@router.get("/capabilities")
def get_release_capabilities():
    return release_capabilities()


@router.get("")
def get_releases(project_name: str | None = None, status: str | None = None, limit: int = Query(default=100, ge=1, le=500)):
    return {"items": [_public_release(item) for item in list_release_candidates(project_name=project_name, status=status, limit=limit)], "production_promotion_allowed": False}


@router.post("")
def create_release(
    body: ReleaseCreateRequest,
    x_improvement_operator_id: str | None = Header(default=None),
    x_improvement_operator_token: str | None = Header(default=None),
):
    _validate_project(body.project_name); operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    try:
        result = create_release_from_verified(project_name=body.project_name, issue_id=body.issue_id, commit_sha=body.commit_sha,
                                              scm_provider=body.scm_provider, scm_target=body.scm_target, require_preview=body.require_preview)
    except KeyError:
        raise HTTPException(status_code=404, detail="Verified repair not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _audit(operator, "release.create", project_name=body.project_name, release_id=result["id"], metadata={"issue_id": body.issue_id})
    return _public_release(result)


@router.post("/cleanup")
def cleanup_releases(
    body: CleanupRequest,
    x_improvement_operator_id: str | None = Header(default=None),
    x_improvement_operator_token: str | None = Header(default=None),
):
    if not body.confirm: raise HTTPException(status_code=400, detail="confirm must be true")
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    result = cleanup_expired_release_workspaces(); _audit(operator, "release.cleanup", metadata=result); return result


@router.get("/{release_id}")
def get_release(release_id: str):
    item = get_release_candidate(release_id)
    if not item: raise HTTPException(status_code=404, detail="Release not found")
    return _public_release(item)


@router.get("/{release_id}/evidence")
def get_release_evidence(release_id: str):
    try: return _public_evidence(release_evidence(release_id))
    except KeyError: raise HTTPException(status_code=404, detail="Release not found")


@router.post("/{release_id}/run")
def run_release(
    release_id: str,
    x_improvement_operator_id: str | None = Header(default=None),
    x_improvement_operator_token: str | None = Header(default=None),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    release = get_release_candidate(release_id)
    if not release: raise HTTPException(status_code=404, detail="Release not found")
    try: result = run_release_pipeline(release_id)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc))
    _audit(operator, "release.run", project_name=release["project_name"], release_id=release_id, metadata={"status": (result.get("release") or {}).get("status")})
    if isinstance(result.get("release"), dict): result["release"] = _public_release(result["release"])
    return result


@router.post("/{release_id}/vulnerabilities")
def upload_vulnerability_report(
    release_id: str, body: dict[str, Any],
    x_improvement_operator_id: str | None = Header(default=None),
    x_improvement_operator_token: str | None = Header(default=None),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token); release = get_release_candidate(release_id)
    if not release: raise HTTPException(status_code=404, detail="Release not found")
    try: result = ingest_vulnerability_report(release_id, body)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))
    _audit(operator, "release.vulnerability_evidence", project_name=release["project_name"], release_id=release_id, metadata={"passed": result.get("passed"), "counts": result.get("counts")})
    return result


@router.post("/{release_id}/preview")
def register_preview(
    release_id: str, body: PreviewRequest,
    x_improvement_operator_id: str | None = Header(default=None),
    x_improvement_operator_token: str | None = Header(default=None),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token); release = get_release_candidate(release_id)
    if not release: raise HTTPException(status_code=404, detail="Release not found")
    try: result = create_or_register_preview(release_id, preview_url=body.preview_url, provider=body.provider)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))
    _audit(operator, "release.preview.register", project_name=release["project_name"], release_id=release_id, metadata={"provider": body.provider})
    return _public_preview(result)


@router.post("/{release_id}/promote-staging")
def promote_release_to_staging(
    release_id: str, body: StagingPromotionRequest,
    x_improvement_operator_id: str | None = Header(default=None),
    x_improvement_operator_token: str | None = Header(default=None),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token); release = get_release_candidate(release_id)
    if not release: raise HTTPException(status_code=404, detail="Release not found")
    try: result = promote_staging_ready(release_id, confirm=body.confirm)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc))
    _audit(operator, "release.promote_staging", project_name=release["project_name"], release_id=release_id, metadata={"production_promotion_allowed": False})
    if isinstance(result.get("release"), dict): result["release"] = _public_release(result["release"])
    return result


@router.post("/{release_id}/reject")
def reject_release_candidate(
    release_id: str, body: RejectRequest,
    x_improvement_operator_id: str | None = Header(default=None),
    x_improvement_operator_token: str | None = Header(default=None),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token); release = get_release_candidate(release_id)
    if not release: raise HTTPException(status_code=404, detail="Release not found")
    result = reject_release(release_id, reason=body.reason)
    _audit(operator, "release.reject", project_name=release["project_name"], release_id=release_id, metadata={"reason": body.reason})
    return _public_release(result)
