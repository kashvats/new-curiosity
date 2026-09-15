"""Part 13 staging deployment, validation and release-handoff orchestration."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from app.improvement_release_orchestrator import _release_dir
from app.improvement_release_security import sign_digest
from app.improvement_release_store import (
    create_preview_environment, get_preview_environment, get_release_candidate, list_preview_environments,
    release_evidence, store_release_check, update_preview_environment, update_release_candidate,
)
from app.database import get_db, init_database
from app.improvement_scheduler_integrations import queue_status_publication
from app.improvement_staging_providers import (
    build_deployment_manifest, execute_deployment, promote_oci_to_staging, provider_capabilities,
    rollback_deployment, trigger_ci,
)
from app.improvement_staging_security import (
    build_release_attestation_summary, build_slsa_provenance, canonical_digest, cosign_attest,
)
from app.improvement_staging_store import (
    create_production_release_request, create_staging_deployment, get_staging_deployment,
    list_attestations, list_production_release_requests, list_staging_deployments, update_staging_deployment,
)
from app.safe_commands import run_safe_command


def staging_capabilities() -> Dict[str, Any]:
    return {
        **provider_capabilities(),
        "slsa_provenance": True,
        "cosign_attestations": True,
        "staging_tests": ["smoke", "api", "e2e"],
        "preview_teardown": True,
        "staging_rollback": True,
        "production_release_request": True,
        "production_deployment_supported": False,
        "automatic_production_promotion_enabled": False,
    }


def _release_or_raise(release_id: str) -> Dict[str, Any]:
    release=get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    return release


def _require_staging_ready(release: Dict[str, Any]) -> None:
    if release.get("status") not in {"staging_ready", "staging_validated"}:
        raise ValueError(f"Release must be staging_ready before deployment; status={release.get('status')}")



def _preview_expires_at() -> str:
    from app.config import settings
    ttl=max(1,int(getattr(settings,"IMPROVEMENT_RELEASE_PREVIEW_TTL_HOURS",24)))
    return (datetime.now(timezone.utc)+timedelta(hours=ttl)).isoformat()

def _validate_preview_url(url: str | None) -> str | None:
    if not url: return None
    parsed=urlparse(str(url))
    if parsed.scheme == "https" and parsed.netloc: return str(url)
    if parsed.scheme == "http" and parsed.hostname in {"localhost","127.0.0.1","::1"}: return str(url)
    raise ValueError("Staging preview URL must use HTTPS (localhost HTTP is allowed for development)")


def trigger_release_ci(release_id: str, *, provider: str, ref: str, workflow: str | None = None,
                       variables: Dict[str,str] | None = None) -> Dict[str, Any]:
    release=_release_or_raise(release_id); _require_staging_ready(release)
    target=str(release.get("scm_target") or "")
    if not target: raise ValueError("Release has no scm_target configured")
    result=trigger_ci(provider=provider,target=target,ref=ref,workflow=workflow,variables=variables)
    store_release_check(release_id,check_type="staging_ci_trigger",status="passed" if result.get("status") in {"triggered","planned"} else "failed",details=result)
    return result


def promote_release_oci(release_id: str, *, source_ref: str, destination_ref: str) -> Dict[str, Any]:
    release=_release_or_raise(release_id); _require_staging_ready(release)
    result=promote_oci_to_staging(source_ref=source_ref,destination_ref=destination_ref)
    store_release_check(release_id,check_type="staging_oci_promotion",status="passed" if result.get("status") in {"planned","promoted"} else "failed",details=result)
    return result


def deploy_release_to_staging(release_id: str, *, provider: str, image_ref: str | None = None,
                              namespace: str = "ai-staging", cluster: str | None = None,
                              service: str | None = None, task_definition: str | None = None,
                              preview_url: str | None = None) -> Dict[str, Any]:
    release=_release_or_raise(release_id); _require_staging_ready(release)
    preview_url=_validate_preview_url(preview_url)
    manifest=build_deployment_manifest(provider=provider,release_id=release_id,image_ref=image_ref,namespace=namespace,
                                       cluster=cluster,service=service,task_definition=task_definition)
    deployment=create_staging_deployment(release_id=release_id,provider=provider,manifest=manifest)
    manifest_path=None
    if provider == "kubernetes":
        path=_release_dir(release_id)/f"staging-{deployment['id']}.json"
        path.write_text(json.dumps({"apiVersion":"v1","kind":"List","items":manifest.get("resources",[])},indent=2),encoding="utf-8")
        manifest_path=str(path)
    result=execute_deployment(manifest,manifest_path=manifest_path)
    status=str(result.get("status") or "planned")
    if provider == "external" and preview_url:
        status="ready"
    updated=update_staging_deployment(deployment["id"],status=status,deployment_ref=result.get("deployment_ref"),preview_url=preview_url,
                                      evidence={"provider_result":result,"manifest_path_internal":manifest_path})
    if preview_url:
        create_preview_environment(release_id,provider=provider,preview_url=preview_url,status="ready" if status=="ready" else "provisioning",
                                   expires_at=_preview_expires_at(), metadata={"deployment_id":deployment["id"]})
    store_release_check(release_id,check_type="staging_deployment",status="passed" if status=="ready" else "pending",details={"deployment_id":deployment["id"],"provider":provider,"status":status})
    return updated


def record_deployment_evidence(deployment_id: str, *, status: str, deployment_ref: str | None = None,
                               preview_url: str | None = None, evidence: Dict[str,Any] | None = None) -> Dict[str,Any]:
    deployment=get_staging_deployment(deployment_id)
    if not deployment: raise KeyError(deployment_id)
    if status not in {"ready","failed","provisioning"}: raise ValueError("status must be ready, failed, or provisioning")
    preview_url=_validate_preview_url(preview_url)
    updated=update_staging_deployment(deployment_id,status=status,deployment_ref=deployment_ref,preview_url=preview_url,evidence=evidence or {})
    if preview_url:
        create_preview_environment(deployment["release_id"],provider=deployment["provider"],preview_url=preview_url,status="ready" if status=="ready" else status,
                                   expires_at=_preview_expires_at(), metadata={"deployment_id":deployment_id,"evidence_registered":True})
    store_release_check(deployment["release_id"],check_type="staging_deployment_evidence",status="passed" if status=="ready" else status,details={"deployment_id":deployment_id,"status":status,"deployment_ref":deployment_ref})
    return updated


def run_staging_tests(deployment_id: str, *, checks: List[Dict[str,Any]]) -> Dict[str,Any]:
    deployment=get_staging_deployment(deployment_id)
    if not deployment: raise KeyError(deployment_id)
    if deployment.get("status") not in {"ready","validated"}: raise ValueError("Staging deployment must be ready before tests")
    release=_release_or_raise(deployment["release_id"])
    workspace=Path(str(release.get("workspace_path") or ""))
    if not workspace.is_dir(): raise ValueError("Release workspace is unavailable; rerun the release pipeline before staging tests")
    if not checks or len(checks)>20: raise ValueError("Provide between 1 and 20 staging checks")
    results=[]; all_passed=True
    for spec in checks:
        kind=str(spec.get("kind") or "smoke").lower()
        if kind not in {"smoke","api","e2e"}: raise ValueError("Staging check kind must be smoke, api, or e2e")
        args=spec.get("args")
        if not isinstance(args,list): raise ValueError("Staging check args must be a string array")
        result=run_safe_command(workspace,args,cwd=spec.get("cwd"),timeout_seconds=spec.get("timeout_seconds")).to_dict()
        result["kind"]=kind; results.append(result); all_passed=all_passed and bool(result.get("passed"))
        store_release_check(release["id"],check_type=f"staging_{kind}",status="passed" if result.get("passed") else "failed",details={"deployment_id":deployment_id,"result":result})
    if all_passed:
        if not any(a.get("kind")=="slsa_provenance" for a in list_attestations(release["id"])):
            build_slsa_provenance(release["id"])
        update_staging_deployment(deployment_id,status="validated",evidence={**(deployment.get("evidence") or {}),"staging_tests":results})
        update_release_candidate(release["id"],status="staging_validated")
        provider=str(release.get("scm_provider") or ""); target=str(release.get("scm_target") or ""); sha=str(release.get("commit_sha") or "")
        if provider in {"github","gitlab"} and target and sha:
            queue_status_publication(provider=provider,project_name=release["project_name"],commit_sha=sha,target=target,state="success",
                                     description="Staging deployment and validation passed",context="ai-coding-assistant/staging-validation")
    else:
        update_staging_deployment(deployment_id,status="validation_failed",evidence={**(deployment.get("evidence") or {}),"staging_tests":results})
        update_release_candidate(release["id"],status="staging_validation_failed",failure_reason="One or more staging checks failed")
    return {"passed":all_passed,"deployment":get_staging_deployment(deployment_id),"checks":results,"production_deployment_supported":False}


def rollback_staging(deployment_id: str) -> Dict[str,Any]:
    deployment=get_staging_deployment(deployment_id)
    if not deployment: raise KeyError(deployment_id)
    manifest=deployment.get("manifest") or {}; path=(deployment.get("evidence") or {}).get("manifest_path_internal")
    result=rollback_deployment(manifest,manifest_path=path)
    updated=update_staging_deployment(deployment_id,status=str(result.get("status") or "rolled_back"),rolled_back=True,evidence={**(deployment.get("evidence") or {}),"rollback":result})
    for preview in list_preview_environments(deployment["release_id"]):
        if (preview.get("metadata") or {}).get("deployment_id") == deployment_id and preview.get("status") not in {"torn_down","expired"}:
            update_preview_environment(preview["id"],status="torn_down")
    store_release_check(deployment["release_id"],check_type="staging_rollback",status="passed",details={"deployment_id":deployment_id,"provider_result":result})
    return updated


def teardown_preview(preview_id: str) -> Dict[str,Any]:
    from app.improvement_release_store import get_preview_environment
    preview=get_preview_environment(preview_id)
    if not preview: raise KeyError(preview_id)
    updated=update_preview_environment(preview_id,status="torn_down")
    store_release_check(preview["release_id"],check_type="preview_teardown",status="passed",details={"preview_id":preview_id,"provider":preview.get("provider")})
    return updated


def teardown_expired_previews(*, now: datetime | None = None) -> Dict[str,Any]:
    """Tear down expired Part 12/13 preview records and linked staging deployments.

    Intended for the leader-elected scheduler tick when explicitly enabled. It never
    touches production and preserves release/attestation evidence.
    """
    current=now or datetime.now(timezone.utc); init_database(); candidates=[]
    with get_db() as conn:
        rows=conn.execute("SELECT id, expires_at, status FROM improvement_preview_environments WHERE expires_at IS NOT NULL AND status NOT IN ('torn_down','expired','destroyed') ORDER BY expires_at").fetchall()
    for row in rows:
        try: expires=datetime.fromisoformat(str(row['expires_at']).replace('Z','+00:00'))
        except Exception: continue
        if expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
        if expires <= current: candidates.append(str(row['id']))
    torn=[]; errors=[]
    for preview_id in candidates:
        preview=get_preview_environment(preview_id)
        if not preview: continue
        deployment_id=str((preview.get('metadata') or {}).get('deployment_id') or '')
        try:
            if deployment_id:
                deployment=get_staging_deployment(deployment_id)
                if deployment and deployment.get('status') not in {'rolled_back','rollback_requested'}:
                    rollback_staging(deployment_id)
                else:
                    update_preview_environment(preview_id,status='torn_down')
            else:
                update_preview_environment(preview_id,status='torn_down')
            torn.append(preview_id)
        except Exception as exc:
            errors.append({'preview_id':preview_id,'error':str(exc)[:500]})
    return {'expired_candidates':len(candidates),'torn_down':torn,'errors':errors,'production_deployment_supported':False}


def generate_slsa_attestation(release_id: str) -> Dict[str,Any]:
    release=_release_or_raise(release_id); _require_staging_ready(release)
    result=build_slsa_provenance(release_id)
    store_release_check(release_id,check_type="slsa_provenance",status="passed",details={"attestation_id":result["id"],"digest_sha256":result["digest_sha256"]})
    return result


def attest_release_image(release_id: str, *, image_ref: str) -> Dict[str,Any]:
    _release_or_raise(release_id)
    result=cosign_attest(release_id=release_id,image_ref=image_ref)
    store_release_check(release_id,check_type="cosign_attestation",status="passed" if result.get("status") in {"passed","skipped"} else "failed",details=result)
    return result


def request_production_release(release_id: str, *, operator: Dict[str,Any], confirm: bool,
                               notes: str | None = None) -> Dict[str,Any]:
    if not confirm: raise ValueError("confirm must be true")
    from app.config import settings
    if bool(getattr(settings,"IMPROVEMENT_PRODUCTION_REQUEST_REQUIRE_VERIFIED_OPERATOR",True)) and not bool(operator.get("verified")):
        raise ValueError("A verified operator identity is required for a production release request")
    allowed={v.strip() for v in str(getattr(settings,"IMPROVEMENT_PRODUCTION_REQUEST_ALLOWED_ROLES","release-manager,maintainer")).split(",") if v.strip()}
    if allowed and str(operator.get("role") or "") not in allowed:
        raise ValueError("Operator role is not authorized to create a production release request")
    release=_release_or_raise(release_id)
    if release.get("status") != "staging_validated": raise ValueError("Release must be staging_validated before a production release request can be created")
    deployments=list_staging_deployments(release_id=release_id)
    if not any(d.get("status")=="validated" for d in deployments): raise ValueError("A validated staging deployment is required")
    attestations=list_attestations(release_id)
    if not any(a.get("kind")=="slsa_provenance" for a in attestations): raise ValueError("SLSA provenance is required")
    evidence={"release":release_evidence(release_id),"deployments":deployments,"attestations":attestations}
    digest=canonical_digest(evidence)
    signature=sign_digest(digest,context=f"release:{release_id}:production-release-request")
    if bool(getattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE",True)) and not signature.get("signed"):
        raise ValueError("A release signing key is required for the production release request")
    item=create_production_release_request(release_id=release_id,requested_by=str(operator.get("operator_id") or "unknown"),
                                           role=str(operator.get("role") or "unknown"),evidence_digest=digest,
                                           request={"notes":(notes or "")[:2000],"production_deployment_executed":False,"human_authorized_handoff":True,
                                                    "evidence_signature":signature})
    provider=str(release.get("scm_provider") or ""); target=str(release.get("scm_target") or ""); sha=str(release.get("commit_sha") or "")
    if provider in {"github","gitlab"} and target and sha:
        queue_status_publication(provider=provider,project_name=release["project_name"],commit_sha=sha,target=target,state="success",
                                 description="Staging validated; production release request created",context="ai-coding-assistant/release-request")
    store_release_check(release_id,check_type="production_release_request",status="passed",details={"request_id":item["id"],"evidence_digest":digest,"production_deployment_executed":False})
    return {"request":item,"production_deployment_executed":False,"production_deployment_supported":False}


def staging_release_evidence(release_id: str) -> Dict[str,Any]:
    _release_or_raise(release_id)
    return {"release":release_evidence(release_id),"deployments":list_staging_deployments(release_id=release_id),
            "attestations":build_release_attestation_summary(release_id),
            "production_release_requests":list_production_release_requests(release_id=release_id),
            "production_deployment_supported":False}
