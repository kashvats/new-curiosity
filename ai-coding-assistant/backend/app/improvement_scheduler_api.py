"""FastAPI surface for the Part 9 hardened dry-run scheduler control plane."""
from __future__ import annotations

import hmac
import json
from datetime import datetime
from typing import Any, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.improvement_scheduler import run_schedule, scheduler_overview, scheduler_status, scheduler_tick, simulate_schedule
from app.improvement_scheduler_environment import environment_policy
from app.improvement_scheduler_observability import (
    acknowledge_scheduler_alert,
    list_scheduler_alerts,
    list_scheduler_telemetry,
    prometheus_metrics,
    scheduler_metrics_snapshot,
)
from app.improvement_scheduler_integrations import (
    flush_integrations, integration_status, list_integration_deliveries, list_status_publications,
    queue_status_publication, retry_dead_letter,
)
from app.improvement_scheduler_ha import coordination_status
from app.improvement_scheduler_provenance import (
    github_ci_evidence, gitlab_ci_evidence, record_native_delivery, verify_github_webhook, verify_gitlab_webhook,
)
from app.improvement_scheduler_admin import (
    list_disaster_recovery_drills, retention_preview, run_disaster_recovery_drill, run_retention_compaction,
    rotate_disaster_recovery_backups, verify_disaster_recovery_restore,
)
from app.improvement_scheduler_security import (
    legacy_webhook_token_configured,
    list_operator_audit,
    operator_auth_configured,
    record_operator_audit,
    signed_webhook_configured,
    verify_and_record_evidence_delivery,
    verify_operator,
)
from app.improvement_scheduler_store import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_ci_evidence,
    list_leases,
    list_scheduler_runs,
    list_schedules,
    list_slo_evidence,
    set_scheduler_kill_switch,
    store_ci_evidence,
    store_slo_evidence,
    update_schedule,
)
from app.project_paths import resolve_project_root
from app.improvement_scheduler_tracing import list_traces
from app.improvement_secrets import secret_provider_status
from app.improvement_store import request_improvement_cycle_cancel

router = APIRouter(prefix="/improvements", tags=["improvement-scheduler"])


class ScheduleRequest(BaseModel):
    project_name: str = "default"
    name: str = Field(min_length=1, max_length=120)
    interval_minutes: int = Field(default=1440, ge=1, le=525600)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    maintenance_windows: List[dict[str, Any]] = Field(default_factory=list)
    mode: str = Field(default="observe_propose", pattern="^(observe_propose|canary_observe)$")
    environment: str = Field(default="dev", pattern="^(dev|staging|prod)$")
    enabled: bool = True
    require_readiness: bool = True
    require_ci_success: bool = False
    require_slo: bool = False
    max_runs_per_day: int | None = Field(default=None, ge=1, le=100)
    ci_branch: str | None = Field(default=None, max_length=200)
    ci_commit_sha: str | None = Field(default=None, max_length=160)
    bind_ci_to_project_head: bool = False
    request: dict[str, Any] = Field(default_factory=dict)


class ScheduleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    interval_minutes: int | None = Field(default=None, ge=1, le=525600)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    maintenance_windows: List[dict[str, Any]] | None = None
    mode: str | None = Field(default=None, pattern="^(observe_propose|canary_observe)$")
    environment: str | None = Field(default=None, pattern="^(dev|staging|prod)$")
    enabled: bool | None = None
    require_readiness: bool | None = None
    require_ci_success: bool | None = None
    require_slo: bool | None = None
    max_runs_per_day: int | None = Field(default=None, ge=1, le=100)
    ci_branch: str | None = Field(default=None, max_length=200)
    ci_commit_sha: str | None = Field(default=None, max_length=160)
    bind_ci_to_project_head: bool | None = None
    request: dict[str, Any] | None = None


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=500)
    scope: str = Field(default="global", pattern="^(global|project)$")
    project_name: str | None = None
    confirm: bool = False


class CIEvidenceRequest(BaseModel):
    project_name: str = "default"
    provider: str = Field(default="generic", min_length=1, max_length=80)
    event_type: str = Field(default="ci", min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=40)
    commit_sha: str | None = Field(default=None, max_length=160)
    branch: str | None = Field(default=None, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class SLOEvidenceRequest(BaseModel):
    project_name: str = "default"
    source: str = Field(default="generic", min_length=1, max_length=80)
    availability: float | None = Field(default=None, ge=0, le=100)
    error_rate: float | None = Field(default=None, ge=0, le=100)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    error_budget_remaining: float | None = Field(default=None, ge=0, le=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class AlertAcknowledgeRequest(BaseModel):
    note: str = Field(default="", max_length=500)


class IntegrationFlushRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class RetentionCompactRequest(BaseModel):
    confirm: bool = False
    vacuum: bool = False


class DisasterRecoveryDrillRequest(BaseModel):
    confirm: bool = False


class StatusPublicationRequest(BaseModel):
    provider: str = Field(pattern="^(github|gitlab)$")
    project_name: str = "default"
    commit_sha: str = Field(min_length=4, max_length=160)
    target: str = Field(min_length=1, max_length=300)
    state: str = Field(pattern="^(pending|success|failure|error|cancelled)$")
    description: str = Field(default="", max_length=300)
    context: str = Field(default="ai-coding-assistant/scheduler", max_length=120)


class DRRotationRequest(BaseModel):
    confirm: bool = False
    keep: int | None = Field(default=None, ge=1, le=1000)


def _validate_project(project_name: str) -> None:
    try:
        resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _validate_schedule_values(timezone_name: str, interval_minutes: int, maintenance_windows: List[dict[str, Any]], environment: str = "dev") -> None:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {timezone_name}")
    min_interval = int(environment_policy(environment)["min_interval_minutes"])
    if int(interval_minutes) < min_interval:
        raise HTTPException(status_code=400, detail=f"interval_minutes must be >= {min_interval} for {environment}")
    for window in maintenance_windows:
        for key in ("start", "end"):
            raw = str(window.get(key) or "")
            try:
                hour, minute = [int(v) for v in raw.split(":", 1)]
            except Exception:
                raise HTTPException(status_code=400, detail=f"maintenance window {key} must use HH:MM")
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise HTTPException(status_code=400, detail=f"maintenance window {key} must use a valid 24-hour time")


def _require_evidence_auth(token: str | None) -> None:
    """Part 8 legacy token verification retained for backward compatibility."""
    configured = str(settings.IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN or "")
    if configured and not hmac.compare_digest(configured, str(token or "")):
        raise HTTPException(status_code=401, detail="Invalid evidence webhook token")


def _bounded_payload_bytes(value: Any) -> int:
    try:
        size = len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Evidence payload is not JSON serializable")
    if size > int(settings.IMPROVEMENT_EVIDENCE_MAX_BYTES):
        raise HTTPException(status_code=413, detail="Evidence payload exceeds configured size limit")
    return size


def _as_header_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _operator(operator_id: Any, operator_token: Any) -> dict[str, Any]:
    try:
        return verify_operator(_as_header_string(operator_id), _as_header_string(operator_token))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


def _audit(operator: dict[str, Any], action: str, *, project_name: str | None = None, schedule_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    record_operator_audit(operator=operator, action=action, project_name=project_name, schedule_id=schedule_id, metadata=metadata or {})


def _authenticate_evidence(
    *, request_body: dict[str, Any], project_name: str, evidence_type: str,
    token: Any, signature: Any, timestamp: Any, delivery_id: Any,
) -> dict[str, Any]:
    if signed_webhook_configured():
        try:
            return verify_and_record_evidence_delivery(
                project_name=project_name, evidence_type=evidence_type, payload=request_body,
                signature=_as_header_string(signature), timestamp=_as_header_string(timestamp),
                delivery_id=_as_header_string(delivery_id),
            )
        except ValueError as exc:
            message = str(exc)
            status = 409 if "already been processed" in message else 401
            raise HTTPException(status_code=status, detail=message)
    _require_evidence_auth(_as_header_string(token))
    return {"authenticated": legacy_webhook_token_configured(), "method": "legacy_token" if legacy_webhook_token_configured() else "none"}


@router.get("/scheduler/status")
def get_scheduler_status(project_name: str | None = None):
    if project_name:
        _validate_project(project_name)
    return scheduler_overview(project_name)


@router.get("/scheduler/schedules")
def get_schedules(project_name: str | None = None, enabled_only: bool = False):
    if project_name:
        _validate_project(project_name)
    return {"schedules": list_schedules(project_name=project_name, enabled_only=enabled_only), "automatic_source_apply_enabled": False}


@router.post("/scheduler/schedules", status_code=201)
def add_schedule(
    req: ScheduleRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    _validate_project(req.project_name)
    _validate_schedule_values(req.timezone, req.interval_minutes, req.maintenance_windows, req.environment)
    existing = list_schedules(project_name=req.project_name, limit=int(settings.IMPROVEMENT_SCHEDULER_MAX_SCHEDULES_PER_PROJECT) + 1)
    if len(existing) >= int(settings.IMPROVEMENT_SCHEDULER_MAX_SCHEDULES_PER_PROJECT):
        raise HTTPException(status_code=409, detail="Maximum schedules for this project reached")
    forbidden = {"policy", "pause_for_candidate_selection", "experiment_mode", "confirm", "apply"}
    request = {k: v for k, v in req.request.items() if k not in forbidden}
    schedule = create_schedule(
        project_name=req.project_name, name=req.name, interval_minutes=req.interval_minutes,
        timezone_name=req.timezone, maintenance_windows=req.maintenance_windows, mode=req.mode,
        enabled=req.enabled, require_readiness=req.require_readiness, require_ci_success=req.require_ci_success,
        require_slo=req.require_slo, max_runs_per_day=req.max_runs_per_day, request=request,
        environment=req.environment, ci_branch=req.ci_branch, ci_commit_sha=req.ci_commit_sha,
        bind_ci_to_project_head=req.bind_ci_to_project_head,
    )
    _audit(operator, "schedule.create", project_name=req.project_name, schedule_id=schedule["id"], metadata={"environment": req.environment})
    return schedule


@router.put("/scheduler/schedules/{schedule_id}")
def edit_schedule(
    schedule_id: str, req: ScheduleUpdateRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    current = get_schedule(schedule_id)
    if not current:
        raise HTTPException(status_code=404, detail="Schedule not found")
    timezone_name = req.timezone or current["timezone"]
    interval = req.interval_minutes or current["interval_minutes"]
    environment = req.environment or current.get("environment") or "dev"
    windows = current.get("maintenance_windows") if req.maintenance_windows is None else req.maintenance_windows
    _validate_schedule_values(timezone_name, interval, windows or [], environment)
    changes = req.model_dump(exclude_none=True)
    if "request" in changes:
        forbidden = {"policy", "pause_for_candidate_selection", "experiment_mode", "confirm", "apply"}
        changes["request"] = {k: v for k, v in changes["request"].items() if k not in forbidden}
    updated = update_schedule(schedule_id, **changes)
    _audit(operator, "schedule.update", project_name=current["project_name"], schedule_id=schedule_id, metadata={"changes": sorted(changes)})
    return updated


@router.delete("/scheduler/schedules/{schedule_id}")
def remove_schedule(
    schedule_id: str,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    current = get_schedule(schedule_id)
    if not current:
        raise HTTPException(status_code=404, detail="Schedule not found")
    delete_schedule(schedule_id)
    _audit(operator, "schedule.delete", project_name=current["project_name"], schedule_id=schedule_id)
    return {"status": "deleted", "schedule_id": schedule_id}


@router.post("/scheduler/simulate")
def preview_schedule(req: ScheduleRequest, at: str | None = None):
    _validate_project(req.project_name)
    _validate_schedule_values(req.timezone, req.interval_minutes, req.maintenance_windows, req.environment)
    now = None
    if at:
        try:
            now = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="at must be an ISO-8601 timestamp") from exc
    schedule = req.model_dump()
    schedule["id"] = "__preview__"
    return simulate_schedule(schedule, now=now)


@router.get("/scheduler/schedules/{schedule_id}/simulate")
def preview_saved_schedule(schedule_id: str, at: str | None = None):
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    now = None
    if at:
        try:
            now = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="at must be an ISO-8601 timestamp") from exc
    return simulate_schedule(schedule, now=now)


@router.post("/scheduler/schedules/{schedule_id}/run-now")
async def run_schedule_now(
    schedule_id: str,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    _audit(operator, "schedule.run_now", project_name=schedule["project_name"], schedule_id=schedule_id)
    return await run_schedule(schedule_id, ignore_due=True)


@router.post("/scheduler/tick")
async def run_scheduler_tick(
    limit: int = Query(20, ge=1, le=100),
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    _audit(operator, "scheduler.tick", metadata={"limit": limit})
    return await scheduler_tick(limit=limit)


@router.get("/scheduler/runs")
def get_scheduler_runs(project_name: str | None = None, schedule_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if project_name:
        _validate_project(project_name)
    return {"runs": list_scheduler_runs(project_name=project_name, schedule_id=schedule_id, limit=limit)}


@router.get("/scheduler/leases")
def get_scheduler_leases():
    return {"leases": list_leases(), "fencing_enabled": True, "coordination": coordination_status()}


@router.get("/scheduler/metrics")
def get_scheduler_metrics(project_name: str | None = None):
    if project_name:
        _validate_project(project_name)
    return scheduler_metrics_snapshot(project_name)


@router.get("/scheduler/metrics/prometheus", response_class=PlainTextResponse)
def get_scheduler_prometheus_metrics(project_name: str | None = None):
    if project_name:
        _validate_project(project_name)
    return prometheus_metrics(project_name)


@router.get("/scheduler/telemetry")
def get_scheduler_telemetry(project_name: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if project_name:
        _validate_project(project_name)
    return {"telemetry": list_scheduler_telemetry(project_name=project_name, limit=limit)}


@router.get("/scheduler/alerts")
def get_scheduler_alerts(project_name: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if project_name:
        _validate_project(project_name)
    return {"alerts": list_scheduler_alerts(project_name=project_name, status=status, limit=limit)}


@router.post("/scheduler/alerts/{alert_id}/ack")
def acknowledge_alert(
    alert_id: str, req: AlertAcknowledgeRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    item = acknowledge_scheduler_alert(alert_id, operator_id=str(operator["operator_id"]))
    if not item:
        raise HTTPException(status_code=404, detail="Alert not found")
    _audit(operator, "alert.acknowledge", project_name=item.get("project_name"), schedule_id=item.get("schedule_id"), metadata={"alert_id": alert_id, "note": req.note})
    return item


@router.get("/scheduler/audit")
def scheduler_audit(project_name: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if project_name:
        _validate_project(project_name)
    return {"events": list_operator_audit(project_name=project_name, limit=limit)}


@router.post("/scheduler/kill-switch")
def scheduler_kill_switch(
    req: KillSwitchRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to change the scheduler kill switch")
    scope = "global"
    if req.scope == "project":
        if not req.project_name:
            raise HTTPException(status_code=400, detail="project_name is required for project scope")
        _validate_project(req.project_name)
        scope = f"project:{req.project_name}"
    control = set_scheduler_kill_switch(enabled=req.enabled, reason=req.reason, scope=scope)
    cancelled_cycle_ids = []
    if req.enabled:
        active = list_scheduler_runs(project_name=req.project_name if req.scope == "project" else None, limit=500)
        for run in active:
            if run.get("status") != "started" or not run.get("cycle_id"):
                continue
            try:
                request_improvement_cycle_cancel(run["cycle_id"])
                cancelled_cycle_ids.append(run["cycle_id"])
            except KeyError:
                pass
    _audit(operator, "scheduler.kill_switch", project_name=req.project_name, metadata={"enabled": req.enabled, "scope": scope, "reason": req.reason, "cancelled_cycles": cancelled_cycle_ids})
    return {**control, "cancel_requested_cycle_ids": cancelled_cycle_ids}


@router.post("/evidence/ci", status_code=201)
def ingest_ci_evidence(
    req: CIEvidenceRequest,
    x_improvement_webhook_token: str | None = Header(default=None, alias="X-Improvement-Webhook-Token"),
    x_improvement_signature: str | None = Header(default=None, alias="X-Improvement-Signature"),
    x_improvement_timestamp: str | None = Header(default=None, alias="X-Improvement-Timestamp"),
    x_improvement_delivery_id: str | None = Header(default=None, alias="X-Improvement-Delivery-ID"),
):
    _validate_project(req.project_name)
    body = req.model_dump()
    _bounded_payload_bytes(body)
    auth = _authenticate_evidence(
        request_body=body, project_name=req.project_name, evidence_type="ci", token=x_improvement_webhook_token,
        signature=x_improvement_signature, timestamp=x_improvement_timestamp, delivery_id=x_improvement_delivery_id,
    )
    status = req.status.strip().lower()
    if status not in {"success", "successful", "passed", "pass", "succeeded", "green", "failure", "failed", "error", "pending", "cancelled"}:
        raise HTTPException(status_code=400, detail="Unsupported CI status")
    stored = store_ci_evidence(project_name=req.project_name, provider=req.provider, status=status, event_type=req.event_type, commit_sha=req.commit_sha, branch=req.branch, payload=req.payload)
    return {**stored, "delivery_auth": auth}


@router.get("/evidence/ci")
def ci_evidence(project_name: str = "default", limit: int = Query(50, ge=1, le=500)):
    _validate_project(project_name)
    return {"evidence": list_ci_evidence(project_name, limit=limit)}


@router.post("/evidence/slo", status_code=201)
def ingest_slo_evidence(
    req: SLOEvidenceRequest,
    x_improvement_webhook_token: str | None = Header(default=None, alias="X-Improvement-Webhook-Token"),
    x_improvement_signature: str | None = Header(default=None, alias="X-Improvement-Signature"),
    x_improvement_timestamp: str | None = Header(default=None, alias="X-Improvement-Timestamp"),
    x_improvement_delivery_id: str | None = Header(default=None, alias="X-Improvement-Delivery-ID"),
):
    _validate_project(req.project_name)
    body = req.model_dump()
    _bounded_payload_bytes(body)
    auth = _authenticate_evidence(
        request_body=body, project_name=req.project_name, evidence_type="slo", token=x_improvement_webhook_token,
        signature=x_improvement_signature, timestamp=x_improvement_timestamp, delivery_id=x_improvement_delivery_id,
    )
    if all(value is None for value in (req.availability, req.error_rate, req.latency_p95_ms, req.error_budget_remaining)):
        raise HTTPException(status_code=400, detail="At least one SLO metric is required")
    stored = store_slo_evidence(project_name=req.project_name, source=req.source, availability=req.availability, error_rate=req.error_rate, latency_p95_ms=req.latency_p95_ms, error_budget_remaining=req.error_budget_remaining, payload=req.payload)
    return {**stored, "delivery_auth": auth}


@router.get("/evidence/slo")
def slo_evidence(project_name: str = "default", limit: int = Query(50, ge=1, le=500)):
    _validate_project(project_name)
    return {"evidence": list_slo_evidence(project_name, limit=limit)}


@router.get("/scheduler/integrations")
def get_scheduler_integrations(limit: int = Query(50, ge=1, le=500)):
    return {
        "status": integration_status(),
        "coordination": coordination_status(),
        "secrets": secret_provider_status(),
        "deliveries": list_integration_deliveries(limit=limit),
        "status_publications": list_status_publications(limit=limit),
        "automatic_source_apply_enabled": False,
    }


@router.post("/scheduler/integrations/flush")
def flush_scheduler_integrations(
    req: IntegrationFlushRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    result = flush_integrations(limit=req.limit)
    _audit(operator, "integrations.flush", metadata={"limit": req.limit, "result": result})
    return result


@router.post("/scheduler/integrations/status-publications", status_code=201)
def create_status_publication(
    req: StatusPublicationRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    _validate_project(req.project_name)
    try:
        item = queue_status_publication(**req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(operator, "status_publication.queue", project_name=req.project_name, metadata={"publication_id": item["id"], "provider": req.provider, "state": req.state})
    return item


@router.get("/scheduler/integrations/status-publications")
def get_status_publications(project_name: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=500)):
    if project_name:
        _validate_project(project_name)
    return {"publications": list_status_publications(project_name=project_name, status=status, limit=limit), "automatic_source_apply_enabled": False}


@router.post("/scheduler/integrations/deliveries/{delivery_id}/retry")
def retry_integration_delivery(
    delivery_id: str,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    if not retry_dead_letter(delivery_id):
        raise HTTPException(status_code=404, detail="Dead-letter delivery not found")
    _audit(operator, "integration.retry", metadata={"delivery_id": delivery_id})
    return {"status": "retry_queued", "delivery_id": delivery_id, "automatic_source_apply_enabled": False}


@router.get("/scheduler/traces")
def scheduler_traces(project_name: str | None = None, run_id: str | None = None, trace_id: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    if project_name:
        _validate_project(project_name)
    return {"traces": list_traces(project_name=project_name, run_id=run_id, trace_id=trace_id, limit=limit), "automatic_source_apply_enabled": False}


@router.post("/evidence/github", status_code=201)
async def ingest_github_evidence(
    request: Request, project_name: str = Query("default"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
):
    _validate_project(project_name)
    body = await request.body()
    if len(body) > int(settings.IMPROVEMENT_EVIDENCE_MAX_BYTES):
        raise HTTPException(status_code=413, detail="Evidence payload exceeds configured size limit")
    try:
        verify_github_webhook(body=body, signature=x_hub_signature_256)
        payload = json.loads(body.decode("utf-8"))
        record_native_delivery(provider="github", project_name=project_name, delivery_id=x_github_delivery, body=body)
        normalized = github_ci_evidence(payload, event=x_github_event, delivery_id=x_github_delivery)
    except (ValueError, json.JSONDecodeError) as exc:
        message = str(exc)
        status = 409 if "already been processed" in message else (401 if "signature" in message.lower() else 400)
        raise HTTPException(status_code=status, detail=message)
    stored = store_ci_evidence(project_name=project_name, **normalized)
    return {**stored, "provenance": "github_native", "authenticated": True}


@router.post("/evidence/gitlab", status_code=201)
async def ingest_gitlab_evidence(
    request: Request, project_name: str = Query("default"),
    x_gitlab_token: str | None = Header(default=None, alias="X-Gitlab-Token"),
    x_gitlab_event: str | None = Header(default=None, alias="X-Gitlab-Event"),
    x_gitlab_event_uuid: str | None = Header(default=None, alias="X-Gitlab-Event-UUID"),
):
    _validate_project(project_name)
    body = await request.body()
    if len(body) > int(settings.IMPROVEMENT_EVIDENCE_MAX_BYTES):
        raise HTTPException(status_code=413, detail="Evidence payload exceeds configured size limit")
    try:
        verify_gitlab_webhook(token=x_gitlab_token)
        payload = json.loads(body.decode("utf-8"))
        record_native_delivery(provider="gitlab", project_name=project_name, delivery_id=x_gitlab_event_uuid, body=body)
        normalized = gitlab_ci_evidence(payload, event=x_gitlab_event, delivery_id=x_gitlab_event_uuid)
    except (ValueError, json.JSONDecodeError) as exc:
        message = str(exc)
        status = 409 if "already been processed" in message else (401 if "token" in message.lower() else 400)
        raise HTTPException(status_code=status, detail=message)
    stored = store_ci_evidence(project_name=project_name, **normalized)
    return {**stored, "provenance": "gitlab_native", "authenticated": True}


@router.get("/scheduler/admin/retention/preview")
def scheduler_retention_preview(
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    result = retention_preview()
    _audit(operator, "retention.preview", metadata={"counts": result.get("counts")})
    return result


@router.post("/scheduler/admin/retention/compact")
def scheduler_retention_compact(
    req: RetentionCompactRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to run retention/compaction")
    result = run_retention_compaction(vacuum=req.vacuum)
    _audit(operator, "retention.compact", metadata={"vacuum": req.vacuum, "deleted": result.get("deleted")})
    return result


@router.post("/scheduler/admin/dr-drill")
def scheduler_dr_drill(
    req: DisasterRecoveryDrillRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to run a disaster-recovery drill")
    result = run_disaster_recovery_drill()
    _audit(operator, "dr.drill", metadata={"drill_id": result.get("id"), "status": result.get("status")})
    return result


@router.get("/scheduler/admin/dr-drills")
def scheduler_dr_drills(
    limit: int = Query(50, ge=1, le=200),
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    _operator(x_improvement_operator_id, x_improvement_operator_token)
    return {"drills": list_disaster_recovery_drills(limit=limit), "automatic_source_apply_enabled": False}

@router.post("/scheduler/admin/dr-drills/{drill_id}/verify-restore")
def scheduler_dr_verify_restore(
    drill_id: str,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    try:
        result = verify_disaster_recovery_restore(drill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="DR drill not found") from exc
    _audit(operator, "dr.verify_restore", metadata={"drill_id": drill_id, "verified": result.get("verified")})
    return result


@router.post("/scheduler/admin/dr-backups/rotate")
def scheduler_dr_rotate(
    req: DRRotationRequest,
    x_improvement_operator_id: str | None = Header(default=None, alias="X-Improvement-Operator-ID"),
    x_improvement_operator_token: str | None = Header(default=None, alias="X-Improvement-Operator-Token"),
):
    operator = _operator(x_improvement_operator_id, x_improvement_operator_token)
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to rotate DR backups")
    result = rotate_disaster_recovery_backups(keep=req.keep)
    _audit(operator, "dr.rotate", metadata={"keep": result.get("keep"), "removed": len(result.get("removed") or [])})
    return result

