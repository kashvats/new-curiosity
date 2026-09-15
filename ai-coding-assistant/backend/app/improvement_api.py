"""FastAPI surface for user-triggered, outcome-aware project improvement cycles."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Coroutine, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.dependency_health import analyze_dependency_health
from app.improvement_budget import empty_usage, resolve_cycle_budget
from app.improvement_controller import (
    apply_improvement_cycle,
    is_terminal_improvement_cycle,
    run_improvement_cycle,
    select_improvement_candidate_for_cycle,
)
from app.improvement_learning import strategy_statistics
from app.autonomy_readiness import autonomy_readiness_report
from app.improvement_approvals import approval_requirement_status, approver_registry, list_cycle_approvals, record_cycle_approval
from app.improvement_coverage import coverage_delta, list_coverage_reports, store_coverage_report
from app.improvement_integrity import seal_policy_snapshot, verify_policy_snapshot
from app.improvement_regression_attribution import list_regression_attributions
from app.improvement_governance import list_governance_checks
from app.improvement_policy import (
    candidate_allowed_by_policy, list_improvement_policies, resolved_improvement_policy, save_improvement_policy,
)
from app.improvement_test_impact import test_impact_memory
from app.improvement_store import (
    create_improvement_cycle,
    get_health_snapshot,
    get_improvement_cycle,
    latest_health_snapshot,
    list_improvement_candidates,
    list_improvement_cycles,
    list_improvement_events,
    list_improvement_experiments,
    list_improvement_outcomes,
    discard_improvement_experiment,
    request_improvement_cycle_cancel,
)
from app.project_baselines import create_project_baseline, list_project_baselines, project_drift
from app.project_health import capture_project_health
from app.project_paths import resolve_project_root

router = APIRouter(prefix="/improvements", tags=["improvements"])
_improvement_tasks: set[asyncio.Task] = set()


class ImprovementCycleRequest(BaseModel):
    project_name: str = "default"
    trigger: str = "manual"
    policy: str = Field(default="manual", pattern="^(manual|observe_only)$")
    run_checks: bool = True
    force: bool = False
    allowed_risks: List[str] = Field(default_factory=lambda: ["low", "medium"])
    min_priority: float | None = None
    max_attempts: int | None = Field(default=None, ge=1)
    acceptable_health_score: float | None = None
    pause_for_candidate_selection: bool = False
    experiment_mode: bool = False
    experiment_candidates: int = Field(default=2, ge=1)
    max_candidate_repairs: int | None = Field(default=None, ge=1)
    max_cycle_attempts: int | None = Field(default=None, ge=1)
    max_changed_files: int | None = Field(default=None, ge=1)
    max_patch_bytes: int | None = Field(default=None, ge=1024)


class CandidateSelectionRequest(BaseModel):
    candidate_id: str
    experiment_mode: bool | None = None
    experiment_candidates: int | None = Field(default=None, ge=1)


class ApplyImprovementRequest(BaseModel):
    confirm: bool = False


class BaselineCreateRequest(BaseModel):
    project_name: str = "default"
    label: str = Field(default="approved", min_length=1, max_length=100)
    activate: bool = True


class ImprovementPolicyUpdateRequest(BaseModel):
    policy: dict[str, Any] = Field(default_factory=dict)
    activate: bool = True


class ImprovementApprovalRequest(BaseModel):
    approver_id: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=80)
    token: str = Field(min_length=1, max_length=500)


class CoverageReportRequest(BaseModel):
    project_name: str = "default"
    cycle_id: str | None = None
    phase: str = Field(default="current", pattern="^(baseline|pre_apply|post_apply|current|final)$")
    report_format: str = "auto"
    report: Any


def _track(coro: Coroutine[Any, Any, Any]) -> None:
    async def runner() -> None:
        try:
            await coro
        except Exception:
            # Controllers persist their terminal/error state and events.
            pass
    task = asyncio.create_task(runner())
    _improvement_tasks.add(task)
    task.add_done_callback(_improvement_tasks.discard)


def _schedule(cycle_id: str) -> None:
    _track(run_improvement_cycle(cycle_id))


@router.get("/capabilities")
def improvement_capabilities():
    return {
        "policies": ["manual", "observe_only"],
        "default_policy": settings.IMPROVEMENT_DEFAULT_POLICY,
        "scheduler_enabled": bool(settings.IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED),
        "dry_run_scheduler_control_plane": True,
        "scheduled_modes": ["observe_propose", "canary_observe"],
        "scheduled_source_apply_enabled": False,
        "maintenance_windows": True,
        "scheduler_concurrency_leases": True,
        "scheduler_rate_limits": True,
        "scheduler_kill_switch": True,
        "ci_webhook_evidence": True,
        "slo_error_budget_gates": True,
        "canary_scheduling": True,
        "outcome_learning": True,
        "manual_candidate_override": True,
        "isolated_experiment_mode": True,
        "api_architecture_baselines": True,
        "offline_dependency_health": True,
        "cycle_resource_budgets": True,
        "project_governance_policies": True,
        "protected_api_contracts": True,
        "architecture_invariants": True,
        "repeated_candidate_suppression": True,
        "test_impact_memory": True,
        "cycle_cancel": True,
        "experiment_discard": True,
        "policy_snapshot_integrity": True,
        "policy_snapshot_signing_configured": bool(str(settings.IMPROVEMENT_POLICY_SIGNING_KEY or "")),
        "authenticated_approval_roles": True,
        "approver_registry_configured": bool(approver_registry()),
        "coverage_report_ingestion": True,
        "failure_class_cooldowns": True,
        "historical_risk_escalation": True,
        "cross_cycle_regression_attribution": True,
        "autonomy_readiness_report": True,
        "experiment_max_candidates": settings.IMPROVEMENT_EXPERIMENT_MAX_CANDIDATES,
        "minimum_learning_samples": settings.IMPROVEMENT_MIN_LEARNING_SAMPLES,
        "allowed_risks": [v.strip() for v in str(settings.IMPROVEMENT_ALLOWED_RISKS).split(",") if v.strip()],
        "human_approval_required_for_source_apply": True,
    }


@router.get("/health")
def project_health(project_name: str = "default", run_checks: bool = True, persist: bool = False):
    try:
        resolve_project_root(project_name)
        snapshot = capture_project_health(project_name, run_checks=run_checks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not persist:
        return snapshot
    from app.improvement_store import store_health_snapshot
    return store_health_snapshot(project_name=project_name, snapshot=snapshot, cycle_id=None, phase="manual")


@router.get("/health/latest")
def latest_health(project_name: str = "default"):
    row = latest_health_snapshot(project_name)
    if not row:
        raise HTTPException(status_code=404, detail="No health snapshot found")
    return row


@router.get("/health/{snapshot_id}")
def health_snapshot(snapshot_id: str):
    row = get_health_snapshot(snapshot_id)
    if not row:
        raise HTTPException(status_code=404, detail="Health snapshot not found")
    return row


@router.get("/dependencies")
def dependency_health(project_name: str = "default"):
    try:
        root = resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"project_name": project_name, **analyze_dependency_health(root)}


@router.post("/baselines")
def create_baseline(req: BaselineCreateRequest):
    try:
        resolve_project_root(req.project_name)
        return create_project_baseline(req.project_name, label=req.label, activate=req.activate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baselines")
def baselines(project_name: str = "default", limit: int = Query(50, ge=1, le=200)):
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"baselines": list_project_baselines(project_name, limit=limit)}


@router.get("/drift")
def drift(project_name: str = "default"):
    try:
        resolve_project_root(project_name)
        return project_drift(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/learning/strategies")
def learning_strategies(project_name: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    return {"strategies": strategy_statistics(project_name=project_name, limit=limit)}


@router.get("/policies/{project_name}")
def project_policy(project_name: str):
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return resolved_improvement_policy(project_name)


@router.put("/policies/{project_name}")
def update_project_policy(project_name: str, req: ImprovementPolicyUpdateRequest):
    try:
        resolve_project_root(project_name)
        return save_improvement_policy(project_name, req.policy, activate=req.activate)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/policies/{project_name}/history")
def project_policy_history(project_name: str, limit: int = Query(50, ge=1, le=200)):
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"policies": list_improvement_policies(project_name, limit=limit)}


@router.get("/governance/checks")
def governance_checks(project_name: str | None = None, cycle_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return {"checks": list_governance_checks(project_name=project_name, cycle_id=cycle_id, limit=limit)}


@router.get("/test-impact")
def test_impact(project_name: str = "default", files: str = ""):
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    paths = [v.strip() for v in files.split(",") if v.strip()]
    return test_impact_memory(project_name, paths)


@router.post("/coverage/reports")
def ingest_coverage_report(req: CoverageReportRequest):
    try:
        resolve_project_root(req.project_name)
        if req.cycle_id:
            cycle = get_improvement_cycle(req.cycle_id)
            if not cycle or cycle.get("project_name") != req.project_name:
                raise HTTPException(status_code=400, detail="cycle_id does not belong to project_name")
        return store_coverage_report(project_name=req.project_name, cycle_id=req.cycle_id, phase=req.phase, report=req.report, report_format=req.report_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/coverage/reports")
def coverage_reports(project_name: str = "default", cycle_id: str | None = None, limit: int = Query(50, ge=1, le=500)):
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"reports": list_coverage_reports(project_name, cycle_id=cycle_id, limit=limit)}


@router.get("/coverage/delta")
def coverage_report_delta(project_name: str = "default", cycle_id: str | None = None):
    try:
        resolve_project_root(project_name)
        return coverage_delta(project_name, cycle_id=cycle_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/regressions")
def regression_attributions(project_name: str = "default", limit: int = Query(100, ge=1, le=500)):
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"attributions": list_regression_attributions(project_name, limit=limit)}


@router.get("/readiness")
def autonomy_readiness(project_name: str = "default"):
    try:
        return autonomy_readiness_report(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/cycles", status_code=202)
async def start_improvement_cycle(req: ImprovementCycleRequest):
    try:
        resolve_project_root(req.project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = req.model_dump()
    if payload.get("acceptable_health_score") is None:
        payload.pop("acceptable_health_score", None)
    budget = resolve_cycle_budget(payload)
    policy_snapshot = resolved_improvement_policy(req.project_name)
    policy_integrity = seal_policy_snapshot(policy_snapshot)
    cycle = create_improvement_cycle(
        project_name=req.project_name, trigger=req.trigger, policy=req.policy,
        request=payload, budget=budget, usage=empty_usage(), policy_snapshot=policy_snapshot, policy_integrity=policy_integrity,
    )
    _schedule(cycle["id"])
    return {"status": "queued", "cycle_id": cycle["id"], "policy": req.policy, "budget": budget}


@router.get("/cycles")
def cycles(project_name: str | None = None, limit: int = Query(50, ge=1, le=200)):
    return {"cycles": list_improvement_cycles(project_name=project_name, limit=limit)}


@router.get("/cycles/{cycle_id}")
def cycle_status(cycle_id: str):
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    cycle["candidates"] = list_improvement_candidates(cycle_id)
    cycle["experiments"] = list_improvement_experiments(cycle_id)
    cycle["approvals"] = list_cycle_approvals(cycle_id)
    cycle["policy_integrity_status"] = verify_policy_snapshot(cycle.get("policy_snapshot") or {}, cycle.get("policy_integrity") or {})
    cycle["approval_status"] = approval_requirement_status(cycle_id, (cycle.get("policy_snapshot") or {}).get("policy") or {})
    return cycle


@router.post("/cycles/{cycle_id}/cancel")
def cancel_cycle(cycle_id: str):
    try:
        return request_improvement_cycle_cancel(cycle_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Improvement cycle not found")


@router.post("/cycles/{cycle_id}/select", status_code=202)
async def select_cycle_candidate(cycle_id: str, req: CandidateSelectionRequest):
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    if cycle.get("state") != "WAITING_SELECTION":
        raise HTTPException(status_code=400, detail=f"Cycle is not waiting for selection; current state={cycle.get('state')}")
    candidate = next((item for item in list_improvement_candidates(cycle_id) if item["id"] == req.candidate_id), None)
    if not candidate:
        raise HTTPException(status_code=400, detail="candidate_id does not belong to this cycle")
    request = cycle.get("request") or {}
    project_policy = (cycle.get("policy_snapshot") or resolved_improvement_policy(cycle["project_name"])).get("policy") or {}
    allowed = {str(v).strip().lower() for v in (request.get("allowed_risks") or project_policy.get("allowed_risks") or []) if str(v).strip()}
    threshold = max(
        float(settings.IMPROVEMENT_MIN_PRIORITY if request.get("min_priority") is None else request.get("min_priority")),
        float(project_policy.get("min_priority") or 0.0),
    )
    permitted, reason = candidate_allowed_by_policy(candidate, project_policy)
    if (str(candidate.get("risk") or "medium").lower() not in allowed
            or float(candidate.get("priority_score") or 0.0) < threshold or not permitted):
        raise HTTPException(status_code=400, detail=f"candidate_id does not pass this cycle's policy: {reason or 'risk_or_priority'}")
    _track(select_improvement_candidate_for_cycle(
        cycle_id, req.candidate_id,
        experiment_mode=req.experiment_mode, experiment_candidates=req.experiment_candidates,
    ))
    return {"status": "queued", "cycle_id": cycle_id, "candidate_id": req.candidate_id}


@router.get("/cycles/{cycle_id}/experiments")
def cycle_experiments(cycle_id: str):
    if not get_improvement_cycle(cycle_id):
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    return {"experiments": list_improvement_experiments(cycle_id)}


@router.post("/cycles/{cycle_id}/experiments/{experiment_id}/discard")
def discard_experiment(cycle_id: str, experiment_id: str):
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    experiment = next((item for item in list_improvement_experiments(cycle_id) if item["id"] == experiment_id), None)
    if not experiment:
        raise HTTPException(status_code=404, detail="Improvement experiment not found")
    if experiment.get("candidate_id") == cycle.get("selected_candidate_id") and cycle.get("state") == "WAITING_APPROVAL":
        raise HTTPException(status_code=400, detail="Selected winning experiment cannot be discarded; cancel the cycle instead")
    try:
        return discard_improvement_experiment(experiment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Improvement experiment not found")


@router.get("/cycles/{cycle_id}/events")
def cycle_events(cycle_id: str, after_seq: int = Query(0, ge=0)):
    if not get_improvement_cycle(cycle_id):
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    return {"events": list_improvement_events(cycle_id, after_seq=after_seq)}


@router.get("/cycles/{cycle_id}/events/stream")
async def cycle_event_stream(cycle_id: str, after_seq: int = Query(0, ge=0)):
    if not get_improvement_cycle(cycle_id):
        raise HTTPException(status_code=404, detail="Improvement cycle not found")

    async def stream():
        cursor = int(after_seq)
        idle_ticks = 0
        while True:
            events = list_improvement_events(cycle_id, after_seq=cursor, limit=200)
            if events:
                idle_ticks = 0
                for event in events:
                    cursor = max(cursor, int(event["seq"]))
                    yield f"id: {event['seq']}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            else:
                idle_ticks += 1
            cycle = get_improvement_cycle(cycle_id)
            if is_terminal_improvement_cycle(cycle) and not events:
                yield f"event: end\ndata: {json.dumps({'state': cycle.get('state') if cycle else None, 'last_seq': cursor})}\n\n"
                break
            if idle_ticks >= 20:
                idle_ticks = 0
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/cycles/{cycle_id}/approve")
def approve_cycle(cycle_id: str, req: ImprovementApprovalRequest):
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    if cycle.get("state") != "WAITING_APPROVAL":
        raise HTTPException(status_code=400, detail=f"Cycle is not waiting for approval; current state={cycle.get('state')}")
    policy = (cycle.get("policy_snapshot") or {}).get("policy") or {}
    allowed_roles = set(str(v).lower() for v in ((policy.get("approval") or {}).get("required_roles") or []))
    if allowed_roles and req.role.lower() not in allowed_roles:
        raise HTTPException(status_code=403, detail="Approver role is not permitted by this cycle policy")
    try:
        approval = record_cycle_approval(cycle_id=cycle_id, project_name=cycle["project_name"], approver_id=req.approver_id, role=req.role, token=req.token)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"approval": approval, "status": approval_requirement_status(cycle_id, policy)}


@router.get("/cycles/{cycle_id}/approvals")
def cycle_approvals(cycle_id: str):
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    policy = (cycle.get("policy_snapshot") or {}).get("policy") or {}
    return {"approvals": list_cycle_approvals(cycle_id), "status": approval_requirement_status(cycle_id, policy)}


@router.post("/cycles/{cycle_id}/apply")
def apply_cycle(cycle_id: str, req: ApplyImprovementRequest):
    try:
        return apply_improvement_cycle(cycle_id, confirm=req.confirm)
    except KeyError:
        raise HTTPException(status_code=404, detail="Improvement cycle not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/outcomes")
def outcomes(project_name: str | None = None, cycle_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return {"outcomes": list_improvement_outcomes(project_name=project_name, cycle_id=cycle_id, limit=limit)}
