"""Part 14 production release governance plane.

The module can authorize and package a previously validated release for an independent
production deployer. It deliberately has no production deployment client, credentials,
or command execution path.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import uuid
from zoneinfo import ZoneInfo

from app.config import settings
from app.improvement_release_security import sign_digest, verify_digest_signature
from app.improvement_release_store import get_release_candidate
from app.improvement_staging_security import canonical_digest
from app.improvement_staging_store import get_production_release_request
from app.improvement_production_governance_store import (
    add_governance_approval, create_deployment_package, create_governance_case, create_release_train,
    get_deployment_package, get_governance_case, get_release_train, list_deployment_packages,
    list_governance_approvals, list_governance_cases, list_governance_events, list_release_trains,
    lock_governance_case, record_governance_event, set_case_status, set_release_train_status,
    update_case_inputs, create_deployment_authorization, get_deployment_authorization,
    list_deployment_authorizations,
)


def _csv(name: str, default: str) -> set[str]:
    return {v.strip() for v in str(getattr(settings,name,default) or default).split(",") if v.strip()}


def production_governance_capabilities() -> Dict[str, Any]:
    return {
        "part": 14,
        "multi_person_approval": True,
        "evidence_bound_approvals": True,
        "release_locks": True,
        "change_ticket_references": True,
        "release_trains": True,
        "freeze_windows": True,
        "rollout_plan_generation": ["canary","blue_green","rolling"],
        "signed_deployment_packages": True,
        "deployment_package_audience": str(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_DEPLOYER_AUDIENCE","independent-production-deployer")),
        "minimum_approvals": max(1,int(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_MIN_APPROVALS",2))),
        "required_roles": sorted(_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_REQUIRED_ROLES","release-manager,ops")),
        "production_credentials_stored": False,
        "production_deployment_supported": False,
        "automatic_production_deployment_enabled": False,
        "artifact_binding_supported": True,
        "fresh_deployment_authorizations": True,
        "authorization_ttl_minutes": max(1, int(getattr(settings,"IMPROVEMENT_PRODUCTION_AUTHORIZATION_TTL_MINUTES",10))),
        "production_outcome_learning_supported": True,
    }


def _require_verified_operator(operator: Dict[str,Any], *, allowed_roles: set[str] | None = None) -> None:
    if not bool(operator.get("verified")):
        raise ValueError("A verified operator identity is required for production governance")
    if allowed_roles and str(operator.get("role") or "") not in allowed_roles:
        raise ValueError("Operator role is not authorized for this production-governance action")


def _case_or_raise(case_id: str) -> Dict[str,Any]:
    case=get_governance_case(case_id)
    if not case: raise KeyError(case_id)
    return case


def _request_or_raise(request_id: str) -> Dict[str,Any]:
    request=get_production_release_request(request_id)
    if not request: raise KeyError(request_id)
    return request


def _release_request_integrity(request: Dict[str,Any]) -> Dict[str,Any]:
    sig=(request.get("request") or {}).get("evidence_signature") or {}
    valid=verify_digest_signature(
        str(request.get("evidence_digest") or ""),
        context=f"release:{request.get('release_id')}:production-release-request",
        signature=sig.get("signature"),
    )
    return {"signed":bool(sig.get("signed")),"valid":bool(valid),"algorithm":sig.get("algorithm")}


def create_case_from_request(production_request_id: str, *, operator: Dict[str,Any]) -> Dict[str,Any]:
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_CREATOR_ROLES","release-manager,maintainer"))
    request=_request_or_raise(production_request_id)
    release=get_release_candidate(str(request.get("release_id") or ""))
    if not release: raise ValueError("Release referenced by production request no longer exists")
    integrity=_release_request_integrity(request)
    if not integrity["valid"]: raise ValueError("Production release request signature is invalid")
    case=create_governance_case(
        production_request_id=production_request_id,release_id=release["id"],project_name=release["project_name"],
        created_by=str(operator.get("operator_id") or "unknown"),
    )
    record_governance_event(case_id=case["id"],event_type="case.created",operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),payload={"request_integrity":integrity})
    return case


def attach_change_ticket(case_id: str, *, system: str, reference: str, url: str | None,
                         operator: Dict[str,Any]) -> Dict[str,Any]:
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_EDITOR_ROLES","release-manager,maintainer,ops"))
    case=_case_or_raise(case_id)
    ref=str(reference or "").strip().upper()
    pattern=str(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_PATTERN",r"^[A-Z][A-Z0-9]+-[0-9]+$"))
    try: matched=bool(re.fullmatch(pattern,ref))
    except re.error as exc: raise ValueError("Configured change-ticket pattern is invalid") from exc
    if not matched: raise ValueError("Change-ticket reference does not match the configured policy")
    ticket={"system":str(system or "custom")[:40],"reference":ref,"url":str(url or "")[:2000] or None}
    updated=update_case_inputs(case_id,change_ticket=ticket,status="draft")
    record_governance_event(case_id=case_id,event_type="change_ticket.set",operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),payload=ticket)
    return updated


def attach_artifact_binding(case_id: str, *, artifact_ref: str, digest_sha256: str, kind: str,
                            operator: Dict[str,Any]) -> Dict[str,Any]:
    """Bind the exact production artifact/task definition into the governance digest.

    This is deliberately evidence-only. The AI backend never pulls/pushes/deploys the artifact.
    """
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_EDITOR_ROLES","release-manager,maintainer,ops"))
    _case_or_raise(case_id)
    ref=str(artifact_ref or "").strip()
    kind=str(kind or "oci_image").strip().lower()
    if kind not in {"oci_image","ecs_task_definition","generic_immutable_artifact"}:
        raise ValueError("artifact kind must be oci_image, ecs_task_definition, or generic_immutable_artifact")
    raw=str(digest_sha256 or "").strip().lower()
    digest=raw[7:] if raw.startswith("sha256:") else raw
    if not re.fullmatch(r"[0-9a-f]{64}",digest):
        raise ValueError("artifact digest must be a SHA-256 hex digest")
    if not ref or len(ref)>2000:
        raise ValueError("artifact_ref is required and must be <= 2000 characters")
    binding={"kind":kind,"artifact_ref":ref,"digest_sha256":digest,"immutable":True}
    updated=update_case_inputs(case_id,artifact_binding=binding,status="draft")
    record_governance_event(case_id=case_id,event_type="artifact_binding.set",operator_id=str(operator.get("operator_id")),
                            role=str(operator.get("role")),payload=binding)
    return updated


def generate_rollout_plan(case_id: str, *, strategy: str, operator: Dict[str,Any]) -> Dict[str,Any]:
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_EDITOR_ROLES","release-manager,maintainer,ops"))
    _case_or_raise(case_id); strategy=str(strategy or "").lower()
    common={
        "strategy":strategy,"environment":"production","execution_owner":"independent-production-deployer",
        "preconditions":["verify signed governance package","verify artifact digest","verify SLO/error budget","verify change window"],
        "rollback_triggers":["availability below SLO","error-rate above SLO","critical health check failure","operator abort"],
        "backend_execution_supported":False,
    }
    if strategy=="canary":
        common["stages"]=[
            {"traffic_percent":5,"observe_minutes":15},{"traffic_percent":25,"observe_minutes":20},
            {"traffic_percent":50,"observe_minutes":30},{"traffic_percent":100,"observe_minutes":0},
        ]
    elif strategy=="blue_green":
        common["stages"]=[
            {"action":"deploy_green","traffic_percent":0},{"action":"validate_green","traffic_percent":0},
            {"action":"shift","traffic_percent":10,"observe_minutes":15},{"action":"shift","traffic_percent":50,"observe_minutes":20},
            {"action":"shift","traffic_percent":100,"observe_minutes":30},{"action":"retain_blue_for_rollback","minutes":60},
        ]
    elif strategy=="rolling":
        common.update({"max_unavailable_percent":10,"max_surge_percent":25})
        common["stages"]=[{"batch_percent":25,"observe_minutes":10},{"batch_percent":50,"observe_minutes":15},{"batch_percent":100,"observe_minutes":20}]
    else:
        raise ValueError("strategy must be canary, blue_green, or rolling")
    updated=update_case_inputs(case_id,rollout_plan=common,status="draft")
    record_governance_event(case_id=case_id,event_type="rollout_plan.generated",operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),payload={"strategy":strategy})
    return updated


def create_train(*, name: str, window_start: str, window_end: str, timezone_name: str,
                 operator: Dict[str,Any], metadata: Dict[str,Any] | None = None) -> Dict[str,Any]:
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_TRAIN_ROLES","release-manager,ops"))
    try:
        start=datetime.fromisoformat(str(window_start).replace("Z","+00:00")); end=datetime.fromisoformat(str(window_end).replace("Z","+00:00"))
        ZoneInfo(timezone_name)
    except Exception as exc: raise ValueError("Invalid release-train window or timezone") from exc
    if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None: end=end.replace(tzinfo=timezone.utc)
    if end <= start: raise ValueError("Release-train window_end must be after window_start")
    return create_release_train(name=name,window_start=start.isoformat(),window_end=end.isoformat(),timezone_name=timezone_name,
                                created_by=str(operator.get("operator_id")),metadata=metadata)


def assign_release_train(case_id: str, train_id: str, *, operator: Dict[str,Any]) -> Dict[str,Any]:
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_EDITOR_ROLES","release-manager,maintainer,ops"))
    train=get_release_train(train_id)
    if not train: raise KeyError(train_id)
    if train.get("status") != "open": raise ValueError("Release train is not open")
    updated=update_case_inputs(case_id,release_train_id=train_id,status="draft")
    record_governance_event(case_id=case_id,event_type="release_train.assigned",operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),payload={"release_train_id":train_id})
    return updated


def update_train_status(train_id: str, *, status: str, operator: Dict[str,Any]) -> Dict[str,Any]:
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_TRAIN_ROLES","release-manager,ops"))
    if status not in {"open","frozen","closed"}: raise ValueError("status must be open, frozen, or closed")
    return set_release_train_status(train_id,status)


def _parse_at(value: str | None = None) -> datetime:
    if not value: return datetime.now(timezone.utc)
    parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def freeze_status(*, at: str | None = None) -> Dict[str,Any]:
    current=_parse_at(at); active=[]; raw=str(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON","[]") or "[]")
    try: windows=json.loads(raw)
    except Exception: windows=[]
    if not isinstance(windows,list): windows=[]
    for idx,window in enumerate(windows):
        if not isinstance(window,dict): continue
        reason=str(window.get("reason") or f"freeze-{idx+1}")
        absolute=False
        try:
            if window.get("starts_at") and window.get("ends_at"):
                start=_parse_at(str(window["starts_at"])); end=_parse_at(str(window["ends_at"])); absolute=True
                if start <= current < end: active.append({"reason":reason,"starts_at":start.isoformat(),"ends_at":end.isoformat()})
        except Exception: continue
        if absolute: continue
        try:
            zone=ZoneInfo(str(window.get("timezone") or getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_DEFAULT_TIMEZONE","UTC")))
            local=current.astimezone(zone); days={str(x).lower()[:3] for x in (window.get("days") or [])}
            if days and local.strftime("%a").lower()[:3] not in days: continue
            sh,sm=[int(x) for x in str(window.get("start") or "00:00").split(":",1)]
            eh,em=[int(x) for x in str(window.get("end") or "23:59").split(":",1)]
            minute=local.hour*60+local.minute; start_min=sh*60+sm; end_min=eh*60+em
            inside=(start_min <= minute < end_min) if start_min <= end_min else (minute >= start_min or minute < end_min)
            if inside: active.append({"reason":reason,"timezone":str(zone),"days":sorted(days),"start":f"{sh:02d}:{sm:02d}","end":f"{eh:02d}:{em:02d}"})
        except Exception: continue
    return {"frozen":bool(active),"active_windows":active,"evaluated_at":current.isoformat(),"production_deployment_supported":False}


def _train_evaluation(case: Dict[str,Any], current: datetime) -> Dict[str,Any]:
    train_id=case.get("release_train_id")
    required=bool(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_REQUIRED",False))
    window_required=bool(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_WINDOW_REQUIRED",False))
    if not train_id:
        return {"required":required,"assigned":False,"passed":not required,"reason":"release_train_required" if required else None,"train":None}
    train=get_release_train(str(train_id))
    if not train: return {"required":required,"assigned":True,"passed":False,"reason":"release_train_missing","train":None}
    if train.get("status") != "open": return {"required":required,"assigned":True,"passed":False,"reason":"release_train_not_open","train":train}
    if window_required:
        try:
            start=_parse_at(train.get("window_start")); end=_parse_at(train.get("window_end"))
            if not (start <= current < end): return {"required":required,"assigned":True,"passed":False,"reason":"outside_release_train_window","train":train}
        except Exception: return {"required":required,"assigned":True,"passed":False,"reason":"invalid_release_train_window","train":train}
    return {"required":required,"assigned":True,"passed":True,"reason":None,"train":train}


def _governance_core(case: Dict[str,Any]) -> Dict[str,Any]:
    request=_request_or_raise(str(case.get("production_request_id")))
    release=get_release_candidate(str(case.get("release_id"))) or {}
    train=get_release_train(str(case.get("release_train_id"))) if case.get("release_train_id") else None
    return {
        "schema":"ai-coding-assistant.production-governance.core.v1",
        "case_id":case["id"],"production_request_id":request["id"],"release_id":case["release_id"],
        "project_name":case["project_name"],"commit_sha":release.get("commit_sha"),
        "production_request_evidence_digest":request.get("evidence_digest"),
        "production_request_signature":(request.get("request") or {}).get("evidence_signature"),
        "change_ticket":case.get("change_ticket") or {},"release_train":train,
        "artifact_binding":case.get("artifact_binding") or {},
        "rollout_plan":case.get("rollout_plan") or {},
    }


def current_governance_digest(case_id: str) -> str:
    return canonical_digest(_governance_core(_case_or_raise(case_id)))


def submit_approval(case_id: str, *, operator: Dict[str,Any], decision: str = "approve",
                    comment: str | None = None) -> Dict[str,Any]:
    allowed=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_ALLOWED_APPROVER_ROLES","release-manager,ops,security,maintainer")
    _require_verified_operator(operator,allowed_roles=allowed)
    decision=str(decision).lower()
    if decision not in {"approve","reject"}: raise ValueError("decision must be approve or reject")
    digest=current_governance_digest(case_id)
    approval=add_governance_approval(case_id=case_id,approver_id=str(operator.get("operator_id")),role=str(operator.get("role")),
                                     decision=decision,evidence_digest=digest,comment=comment)
    record_governance_event(case_id=case_id,event_type=f"approval.{decision}",operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),payload={"approval_id":approval["id"],"evidence_digest":digest})
    if decision=="reject": set_case_status(case_id,"rejected")
    else: evaluate_case(case_id,update_status=True)
    return approval


def evaluate_case(case_id: str, *, at: str | None = None, update_status: bool = False) -> Dict[str,Any]:
    case=_case_or_raise(case_id); request=_request_or_raise(str(case.get("production_request_id"))); current=_parse_at(at)
    blockers=[]; warnings=[]
    integrity=_release_request_integrity(request)
    if not integrity["valid"]: blockers.append("production_release_request_signature_invalid")
    change_ticket=case.get("change_ticket") or {}
    if bool(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_REQUIRED",True)) and not change_ticket.get("reference"):
        blockers.append("change_ticket_required")
    rollout=case.get("rollout_plan") or {}
    if not rollout.get("strategy"): blockers.append("rollout_plan_required")
    artifact_binding=case.get("artifact_binding") or {}
    if bool(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_ARTIFACT_BINDING_REQUIRED",False)) and not artifact_binding.get("digest_sha256"):
        blockers.append("artifact_binding_required")
    freeze=freeze_status(at=current.isoformat())
    if freeze["frozen"]: blockers.append("production_freeze_active")
    train_eval=_train_evaluation(case,current)
    if not train_eval["passed"]: blockers.append(str(train_eval.get("reason") or "release_train_blocked"))
    digest=current_governance_digest(case_id)
    approvals=list_governance_approvals(case_id)
    valid=[a for a in approvals if a.get("evidence_digest")==digest and a.get("decision")=="approve"]
    rejects=[a for a in approvals if a.get("evidence_digest")==digest and a.get("decision")=="reject"]
    if rejects: blockers.append("current_evidence_rejected")
    distinct={str(a.get("approver_id")) for a in valid}
    roles={str(a.get("role")) for a in valid}
    min_approvals=max(1,int(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_MIN_APPROVALS",2)))
    required_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_REQUIRED_ROLES","release-manager,ops")
    if len(distinct)<min_approvals: blockers.append("approval_quorum_not_met")
    missing_roles=sorted(required_roles-roles)
    if missing_roles: blockers.append("required_approval_roles_missing")
    stale_count=len([a for a in approvals if a.get("evidence_digest")!=digest])
    if stale_count: warnings.append(f"{stale_count} stale approval(s) do not count after governance evidence changed")
    ready=not blockers
    result={
        "case_id":case_id,"ready_to_lock":ready,"governance_digest":digest,"blockers":blockers,"warnings":warnings,
        "approval_summary":{"valid_approvals":len(valid),"distinct_approvers":len(distinct),"roles":sorted(roles),
                            "minimum_approvals":min_approvals,"required_roles":sorted(required_roles),"missing_roles":missing_roles,
                            "stale_approvals":stale_count},
        "request_integrity":integrity,"freeze":freeze,"release_train":train_eval,
        "production_deployment_supported":False,
    }
    if update_status and not case.get("locked_at") and case.get("status") not in {"rejected","cancelled"}:
        set_case_status(case_id,"approved" if ready else "pending_approval")
    return result


def lock_case(case_id: str, *, operator: Dict[str,Any], confirm: bool) -> Dict[str,Any]:
    if not confirm: raise ValueError("confirm must be true")
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_LOCK_ROLES","release-manager"))
    case=_case_or_raise(case_id)
    if case.get("locked_at"): return {"case":case,"evaluation":evaluate_case(case_id)}
    evaluation=evaluate_case(case_id,update_status=True)
    if not evaluation["ready_to_lock"]: raise ValueError("Governance case is not ready to lock: "+", ".join(evaluation["blockers"]))
    digest=evaluation["governance_digest"]
    signed=sign_digest(digest,context=f"production-governance:{case_id}:lock")
    if bool(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_LOCK_REQUIRE_SIGNATURE",True)) and not signed.get("signed"):
        raise ValueError("A release signing key is required for the immutable governance lock")
    locked=lock_governance_case(case_id,evidence_digest=digest,signature=str(signed.get("signature") or ""),
                                signature_algorithm=str(signed.get("algorithm") or ""),locked_by=str(operator.get("operator_id")))
    record_governance_event(case_id=case_id,event_type="case.locked",operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),payload={"governance_digest":digest})
    return {"case":locked,"evaluation":evaluation,"production_deployment_supported":False}


def _verify_lock(case: Dict[str,Any]) -> None:
    if not case.get("locked_at") or not case.get("governance_digest") or not case.get("lock_signature"):
        raise ValueError("Governance case is not locked")
    current=current_governance_digest(case["id"])
    if current != case.get("governance_digest"):
        raise ValueError("Locked governance evidence has changed")
    if not verify_digest_signature(current,context=f"production-governance:{case['id']}:lock",signature=case.get("lock_signature")):
        raise ValueError("Governance lock signature is invalid")


def build_deployment_package(case_id: str, *, operator: Dict[str,Any], confirm: bool) -> Dict[str,Any]:
    if not confirm: raise ValueError("confirm must be true")
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_GOVERNANCE_PACKAGE_ROLES","release-manager,ops"))
    case=_case_or_raise(case_id); _verify_lock(case)
    evaluation=evaluate_case(case_id)
    # Freeze/train state may change after locking; do not emit a package while newly blocked.
    runtime_blockers=[b for b in evaluation["blockers"] if b in {"production_freeze_active","outside_release_train_window","release_train_not_open","release_train_required","release_train_missing"}]
    if runtime_blockers: raise ValueError("Deployment package is blocked by current release controls: "+", ".join(runtime_blockers))
    request=_request_or_raise(str(case.get("production_request_id"))); release=get_release_candidate(str(case.get("release_id"))) or {}
    approvals=[a for a in list_governance_approvals(case_id) if a.get("evidence_digest")==case.get("governance_digest") and a.get("decision")=="approve"]
    train=get_release_train(str(case.get("release_train_id"))) if case.get("release_train_id") else None
    payload={
        "schema":"ai-coding-assistant.production-deployment-package.v1",
        "audience":str(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_DEPLOYER_AUDIENCE","independent-production-deployer")),
        "case_id":case_id,"release_id":case.get("release_id"),"project_name":case.get("project_name"),
        "commit_sha":release.get("commit_sha"),"scm_provider":release.get("scm_provider"),"scm_target":release.get("scm_target"),
        "production_request":{"id":request.get("id"),"evidence_digest":request.get("evidence_digest")},
        "change_ticket":case.get("change_ticket") or {},"release_train":train,
        "artifact_binding":case.get("artifact_binding") or {},"rollout_plan":case.get("rollout_plan") or {},
        "approvals":[{"approver_id":a.get("approver_id"),"role":a.get("role"),"decision":a.get("decision"),"created_at":a.get("created_at")} for a in approvals],
        "governance_lock":{"digest":case.get("governance_digest"),"signature":case.get("lock_signature"),"algorithm":case.get("lock_signature_algorithm"),"locked_by":case.get("locked_by"),"locked_at":case.get("locked_at")},
        "safety":{"production_credentials_included":False,"backend_can_execute_production":False,"automatic_execution_authorized":False,
                  "independent_deployer_must_verify_signature":True,"human_governance_completed":True},
    }
    digest=canonical_digest(payload); signed=sign_digest(digest,context=f"production-governance:{case_id}:deployment-package")
    if bool(getattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_PACKAGE_REQUIRE_SIGNATURE",True)) and not signed.get("signed"):
        raise ValueError("A release signing key is required for the deployment package")
    item=create_deployment_package(case_id=case_id,digest_sha256=digest,signature=str(signed.get("signature") or ""),
                                   signature_algorithm=str(signed.get("algorithm") or ""),payload=payload)
    record_governance_event(case_id=case_id,event_type="deployment_package.created",operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),payload={"package_id":item["id"],"digest_sha256":digest})
    return {"package":item,"production_credentials_included":False,"production_deployment_supported":False}


def verify_deployment_package(package_id: str) -> Dict[str,Any]:
    package=get_deployment_package(package_id)
    if not package: raise KeyError(package_id)
    payload=package.get("payload") or {}
    computed=canonical_digest(payload)
    digest_matches=computed == package.get("digest_sha256")
    signature_valid=digest_matches and verify_digest_signature(
        computed,context=f"production-governance:{package.get('case_id')}:deployment-package",signature=package.get("signature")
    )
    case=_case_or_raise(str(package.get("case_id")))
    lock_valid=True
    try: _verify_lock(case)
    except ValueError: lock_valid=False
    evaluation=evaluate_case(case["id"])
    runtime_blockers=[b for b in evaluation.get("blockers",[]) if b in {"production_freeze_active","outside_release_train_window","release_train_not_open","release_train_required","release_train_missing"}]
    return {
        "package_id":package_id,"digest_matches":bool(digest_matches),"signature_valid":bool(signature_valid),
        "governance_lock_valid":bool(lock_valid),"runtime_release_controls_clear":not runtime_blockers,
        "runtime_blockers":runtime_blockers,
        "artifact_binding_present":bool((payload.get("artifact_binding") or {}).get("digest_sha256")),
        "valid":bool(digest_matches and signature_valid and lock_valid and not runtime_blockers),
        "production_credentials_included":False,"production_deployment_supported":False,
    }


def issue_deployment_authorization(package_id: str, *, operator: Dict[str,Any], confirm: bool) -> Dict[str,Any]:
    """Issue a short-lived signed runtime authorization for an independent deployer.

    The authorization rechecks current freeze/train controls and binds one exact signed
    package + artifact. It contains no production credentials and cannot execute anything.
    """
    if not confirm: raise ValueError("confirm must be true")
    _require_verified_operator(operator,allowed_roles=_csv("IMPROVEMENT_PRODUCTION_AUTHORIZATION_ROLES","release-manager,ops"))
    package=get_deployment_package(package_id)
    if not package: raise KeyError(package_id)
    verified=verify_deployment_package(package_id)
    if not verified.get("valid"):
        raise ValueError("Deployment package is not currently valid: "+", ".join(verified.get("runtime_blockers") or []))
    payload_src=package.get("payload") or {}
    binding=payload_src.get("artifact_binding") or {}
    if not binding.get("artifact_ref") or not binding.get("digest_sha256"):
        raise ValueError("An immutable production artifact binding is required before deployment authorization")
    now=datetime.now(timezone.utc)
    ttl=max(1,min(int(getattr(settings,"IMPROVEMENT_PRODUCTION_AUTHORIZATION_TTL_MINUTES",10)),60))
    auth_id=str(uuid.uuid4())
    expires=now+timedelta(minutes=ttl)
    authorization={
        "schema":"ai-coding-assistant.production-deployment-authorization.v1",
        "authorization_id":auth_id,"package_id":package_id,"case_id":package.get("case_id"),
        "project_name":payload_src.get("project_name"),"commit_sha":payload_src.get("commit_sha"),
        "package_digest":package.get("digest_sha256"),"artifact_binding":binding,
        "audience":payload_src.get("audience"),"single_use":True,
        "runtime_release_controls_verified":True,"issued_at":now.isoformat(),"expires_at":expires.isoformat(),
        "safety":{"production_credentials_included":False,"backend_can_execute_production":False,
                  "independent_deployer_execution_required":True},
    }
    digest=canonical_digest(authorization)
    signed=sign_digest(digest,context=f"production-deployment-authorization:{auth_id}")
    if not signed.get("signed"):
        raise ValueError("A release signing key is required for deployment authorization")
    item=create_deployment_authorization(authorization_id=auth_id,package_id=package_id,case_id=str(package.get("case_id")),
                                         project_name=str(payload_src.get("project_name") or ""),digest_sha256=digest,
                                         signature=str(signed.get("signature") or ""),signature_algorithm=str(signed.get("algorithm") or ""),
                                         payload=authorization,issued_by=str(operator.get("operator_id") or "unknown"),expires_at=expires.isoformat())
    record_governance_event(case_id=str(package.get("case_id")),event_type="deployment_authorization.issued",
                            operator_id=str(operator.get("operator_id")),role=str(operator.get("role")),
                            payload={"authorization_id":auth_id,"package_id":package_id,"expires_at":expires.isoformat()})
    return {"authorization":item,"production_credentials_included":False,"backend_can_execute_production":False}


def verify_deployment_authorization(authorization_id: str) -> Dict[str,Any]:
    item=get_deployment_authorization(authorization_id)
    if not item: raise KeyError(authorization_id)
    payload=item.get("payload") or {}
    computed=canonical_digest(payload)
    digest_matches=computed == item.get("digest_sha256")
    signature_valid=digest_matches and verify_digest_signature(computed,context=f"production-deployment-authorization:{authorization_id}",signature=item.get("signature"))
    try:
        expires=_parse_at(str(item.get("expires_at"))); unexpired=expires > datetime.now(timezone.utc)
    except Exception:
        unexpired=False
    package_valid=False
    try:
        package_valid=bool(verify_deployment_package(str(item.get("package_id"))).get("valid"))
    except Exception:
        package_valid=False
    return {"authorization_id":authorization_id,"digest_matches":bool(digest_matches),"signature_valid":bool(signature_valid),
            "unexpired":bool(unexpired),"package_valid":bool(package_valid),
            "valid":bool(digest_matches and signature_valid and unexpired and package_valid),
            "production_credentials_included":False,"backend_can_execute_production":False}


def governance_case_detail(case_id: str) -> Dict[str,Any]:
    case=_case_or_raise(case_id)
    return {"case":case,"evaluation":evaluate_case(case_id),"approvals":list_governance_approvals(case_id),
            "events":list_governance_events(case_id),"packages":list_deployment_packages(case_id=case_id),
            "production_deployment_supported":False}
