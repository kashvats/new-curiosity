from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import urlparse

from app.adapters import execute_rolling, rollback as adapter_rollback, validate_target
from app.config import settings
from app.security import canonical_digest, reject_embedded_credentials, sign_receipt, verify_package_and_authorization
from app.store import (
    authorization_used, create_deployment, get_deployment, list_deployments, list_events, list_observations,
    record_event, record_observation, update_deployment, use_authorization,
)

_TERMINAL = {"succeeded", "failed", "rolled_back", "halted", "aborted"}


def capabilities() -> Dict[str, Any]:
    return {
        "part": 15,
        "independent_trust_boundary": True,
        "execution_enabled": bool(settings.PRODUCTION_DEPLOYER_EXECUTION_ENABLED),
        "providers": {
            "kubernetes": {"rolling": "direct_when_enabled", "canary": "evidence_gated_external", "blue_green": "evidence_gated_external"},
            "ecs": {"rolling": "direct_when_enabled", "canary": "evidence_gated_external", "blue_green": "evidence_gated_external"},
            "external": {"rolling": "evidence_gated_external", "canary": "evidence_gated_external", "blue_green": "evidence_gated_external"},
        },
        "automatic_slo_halt": True,
        "automatic_rollback": bool(settings.PRODUCTION_DEPLOYER_AUTO_ROLLBACK_ENABLED),
        "signed_receipts": bool(settings.PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY),
        "credentials_accepted_in_api_payloads": False,
        "ai_backend_production_credentials_required": False,
    }


def verify_handoff(package: Dict[str, Any], authorization: Dict[str, Any]) -> Dict[str, Any]:
    return verify_package_and_authorization(package, authorization)


def create_authorized_deployment(*, package: Dict[str,Any], authorization: Dict[str,Any], provider: str,
                                 target: Dict[str,Any], operator: Dict[str,Any], confirm: bool) -> Dict[str,Any]:
    if not confirm:
        raise ValueError("confirm must be true")
    reject_embedded_credentials(target)
    verified = verify_handoff(package, authorization)
    if not verified["valid"]:
        raise ValueError("Invalid production handoff: " + ", ".join(verified["errors"]))
    auth_id = str(verified["authorization_id"])
    if authorization_used(auth_id):
        raise ValueError("Deployment authorization has already been used")
    payload = package.get("payload") or {}
    strategy = str((payload.get("rollout_plan") or {}).get("strategy") or "")
    if strategy not in {"rolling", "canary", "blue_green"}:
        raise ValueError("Unsupported production rollout strategy")
    target = validate_target(provider, target, verified["artifact_binding"])
    try:
        deployment = create_deployment(package=package, authorization=authorization, target=target, provider=provider,
                                       strategy=strategy, created_by=str(operator.get("operator_id")))
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise ValueError("Deployment authorization is already bound to a deployment") from exc
        raise
    record_event(deployment["id"], "deployment.authorized", operator=operator, payload={"provider":provider,"strategy":strategy})
    return deployment


def execute_deployment(deployment_id: str, *, operator: Dict[str,Any], confirm: bool) -> Dict[str,Any]:
    if not confirm:
        raise ValueError("confirm must be true")
    deployment = get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    if deployment.get("status") != "authorized":
        raise ValueError(f"Deployment must be authorized before execution; status={deployment.get('status')}")
    verified = verify_handoff(deployment["package"], deployment["authorization"])
    if not verified["valid"]:
        raise ValueError("Deployment handoff is no longer valid: " + ", ".join(verified["errors"]))
    strategy = str(deployment["rollout_strategy"])
    if strategy == "rolling" and not bool(settings.PRODUCTION_DEPLOYER_EXECUTION_ENABLED):
        raise ValueError("Production execution is disabled")
    use_authorization(str(deployment["authorization_id"]), deployment_id)
    if strategy in {"canary", "blue_green"}:
        updated = update_deployment(deployment_id, status="awaiting_external_stages", started=True)
        record_event(deployment_id, "deployment.external_stages_required", operator=operator, payload={"strategy":strategy})
        return updated
    try:
        result = execute_rolling(str(deployment["provider"]), deployment["target"])
        updated = update_deployment(deployment_id, status="observing", previous_state=result.get("previous_state") or {}, started=True)
        record_event(deployment_id, "deployment.executed", operator=operator, payload={"provider_result":result})
        return updated
    except Exception as exc:
        updated = update_deployment(deployment_id, status="failed", failure_class="production_deploy_failure", last_error=str(exc), started=True, completed=True)
        record_event(deployment_id, "deployment.failed", operator=operator, payload={"error":str(exc)[:2000]})
        _finalize_receipt(updated)
        return get_deployment(deployment_id) or updated


def evaluate_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    blockers=[]
    health=str(metrics.get("health") or "healthy").lower()
    if health not in {"healthy","ok","pass","passed"}: blockers.append("health_check_failed")
    try:
        if float(metrics.get("availability", 100.0)) < float(settings.PRODUCTION_DEPLOYER_MIN_AVAILABILITY): blockers.append("availability_below_slo")
    except Exception: blockers.append("availability_invalid")
    try:
        if float(metrics.get("error_rate", 0.0)) > float(settings.PRODUCTION_DEPLOYER_MAX_ERROR_RATE): blockers.append("error_rate_above_slo")
    except Exception: blockers.append("error_rate_invalid")
    try:
        if float(metrics.get("latency_p95_ms", 0.0)) > float(settings.PRODUCTION_DEPLOYER_MAX_P95_MS): blockers.append("p95_latency_above_slo")
    except Exception: blockers.append("p95_latency_invalid")
    return {"passed":not blockers,"blockers":blockers}


def observe_deployment(deployment_id: str, *, metrics: Dict[str,Any], operator: Dict[str,Any]) -> Dict[str,Any]:
    deployment=get_deployment(deployment_id)
    if not deployment: raise KeyError(deployment_id)
    if deployment.get("status") in _TERMINAL:
        raise ValueError("Deployment is already terminal")
    gate=evaluate_metrics(metrics)
    obs=record_observation(deployment_id,stage_index=int(deployment.get("current_stage") or 0),metrics=metrics,passed=gate["passed"],blockers=gate["blockers"],created_by=str(operator.get("operator_id")))
    record_event(deployment_id,"deployment.observation",operator=operator,payload=obs)
    if not gate["passed"]:
        update_deployment(deployment_id,status="halted",failure_class="production_slo_halt",last_error=", ".join(gate["blockers"]),completed=True)
        if bool(settings.PRODUCTION_DEPLOYER_AUTO_ROLLBACK_ENABLED):
            return rollback_deployment(deployment_id,operator=operator,confirm=True,reason="automatic_slo_rollback")
        _finalize_receipt(get_deployment(deployment_id) or deployment)
    elif deployment.get("status") == "observing":
        update_deployment(deployment_id,status="succeeded",completed=True)
        _finalize_receipt(get_deployment(deployment_id) or deployment)
    return get_deployment(deployment_id) or deployment


def advance_external_stage(deployment_id: str, *, metrics: Dict[str,Any], action_status: str, operator: Dict[str,Any], confirm: bool) -> Dict[str,Any]:
    if not confirm: raise ValueError("confirm must be true")
    deployment=get_deployment(deployment_id)
    if not deployment: raise KeyError(deployment_id)
    if deployment.get("status") != "awaiting_external_stages": raise ValueError("Deployment is not waiting for external rollout stages")
    if action_status != "completed": raise ValueError("External stage must be reported as completed")
    gate=evaluate_metrics(metrics)
    stage=int(deployment.get("current_stage") or 0)
    record_observation(deployment_id,stage_index=stage,metrics=metrics,passed=gate["passed"],blockers=gate["blockers"],created_by=str(operator.get("operator_id")))
    if not gate["passed"]:
        update_deployment(deployment_id,status="halted",failure_class="production_slo_halt",last_error=", ".join(gate["blockers"]),completed=True)
        _finalize_receipt(get_deployment(deployment_id) or deployment)
        return get_deployment(deployment_id) or deployment
    stages=((deployment.get("package") or {}).get("payload") or {}).get("rollout_plan",{}).get("stages") or []
    next_stage=stage+1
    if next_stage >= len(stages):
        update_deployment(deployment_id,status="succeeded",current_stage=next_stage,completed=True)
        _finalize_receipt(get_deployment(deployment_id) or deployment)
    else:
        update_deployment(deployment_id,current_stage=next_stage)
    record_event(deployment_id,"deployment.stage_advanced",operator=operator,payload={"stage":stage,"next_stage":next_stage,"total_stages":len(stages)})
    return get_deployment(deployment_id) or deployment


def rollback_deployment(deployment_id: str, *, operator: Dict[str,Any], confirm: bool, reason: str="operator_requested") -> Dict[str,Any]:
    if not confirm: raise ValueError("confirm must be true")
    deployment=get_deployment(deployment_id)
    if not deployment: raise KeyError(deployment_id)
    result=adapter_rollback(str(deployment["provider"]),deployment["target"],deployment.get("previous_state") or {})
    if result.get("status") == "rolled_back":
        status="rolled_back"; failure_class="production_rollback"
    elif result.get("status") == "rollback_requested":
        status="halted"; failure_class="production_rollback_requested"
    else:
        status="failed"; failure_class="production_rollback_failure"
    update_deployment(deployment_id,status=status,failure_class=failure_class,last_error=reason,completed=True)
    record_event(deployment_id,"deployment.rollback",operator=operator,payload={"reason":reason,"provider_result":result})
    _finalize_receipt(get_deployment(deployment_id) or deployment)
    return get_deployment(deployment_id) or deployment


def abort_deployment(deployment_id: str, *, operator: Dict[str,Any], confirm: bool) -> Dict[str,Any]:
    if not confirm: raise ValueError("confirm must be true")
    deployment=get_deployment(deployment_id)
    if not deployment: raise KeyError(deployment_id)
    if deployment.get("status") in _TERMINAL: return deployment
    update_deployment(deployment_id,status="aborted",failure_class="production_operator_abort",completed=True)
    record_event(deployment_id,"deployment.aborted",operator=operator)
    _finalize_receipt(get_deployment(deployment_id) or deployment)
    return get_deployment(deployment_id) or deployment


def _receipt_payload(deployment: Dict[str,Any]) -> Dict[str,Any]:
    observations=list_observations(deployment["id"],limit=100)
    latest_metrics=(observations[0].get("metrics") if observations else {}) or {}
    payload=(deployment.get("package") or {}).get("payload") or {}
    return {
        "schema":"ai-coding-assistant.production-deployment-receipt.v1",
        "deployment_id":deployment["id"],"package_id":deployment["package_id"],"authorization_id":deployment["authorization_id"],
        "case_id":deployment["case_id"],"release_id":deployment["release_id"],"project_name":deployment["project_name"],
        "commit_sha":deployment.get("commit_sha"),"provider":deployment["provider"],"rollout_strategy":deployment["rollout_strategy"],
        "status":deployment["status"],"failure_class":deployment.get("failure_class"),"metrics":latest_metrics,
        "artifact_binding":payload.get("artifact_binding") or {},"started_at":deployment.get("started_at"),
        "completed_at":deployment.get("completed_at"),"generated_at":datetime.now(timezone.utc).isoformat(),
    }


def _publish_receipt(receipt: Dict[str,Any]) -> Dict[str,Any]:
    url=str(settings.PRODUCTION_DEPLOYER_OUTCOME_CALLBACK_URL or "").strip()
    if not url: return {"configured":False,"delivered":False}
    parsed=urlparse(url)
    allowed=parsed.scheme=="https" or (bool(settings.PRODUCTION_DEPLOYER_ALLOW_HTTP_CALLBACK) and parsed.scheme=="http" and parsed.hostname in {"localhost","127.0.0.1","host.docker.internal","backend"})
    if not allowed: return {"configured":True,"delivered":False,"error":"callback_url_not_allowed"}
    body=json.dumps(receipt,sort_keys=True,separators=(",", ":")).encode("utf-8")
    try:
        req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=max(1.0,float(settings.PRODUCTION_DEPLOYER_CALLBACK_TIMEOUT_SECONDS))) as response:
            return {"configured":True,"delivered":200 <= int(response.status) < 300,"status_code":int(response.status)}
    except Exception as exc:
        return {"configured":True,"delivered":False,"error":str(exc)[:1000]}


def _finalize_receipt(deployment: Dict[str,Any]) -> Dict[str,Any]:
    if deployment.get("receipt"): return deployment["receipt"]
    payload=_receipt_payload(deployment); digest=canonical_digest(payload); signed=sign_receipt(digest)
    receipt={"payload":payload,"digest_sha256":digest,"signature":signed.get("signature"),"signature_algorithm":signed.get("algorithm")}
    delivery=_publish_receipt(receipt); receipt["callback"]=delivery
    update_deployment(deployment["id"],receipt=receipt)
    record_event(deployment["id"],"deployment.receipt_created",payload={"digest_sha256":digest,"signed":bool(signed.get("signed")),"callback":delivery})
    return receipt


def deployment_detail(deployment_id: str) -> Dict[str,Any]:
    item=get_deployment(deployment_id)
    if not item: raise KeyError(deployment_id)
    # Never echo package signing keys or production credentials; target was credential-screened on entry.
    return {"deployment":item,"observations":list_observations(deployment_id),"events":list_events(deployment_id)}
