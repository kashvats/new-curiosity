"""FastAPI surface for Part 13 staging providers and release handoff."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.improvement_release_store import get_release_candidate
from app.improvement_scheduler_security import record_operator_audit, verify_operator
from app.improvement_staging_orchestrator import (
    attest_release_image, deploy_release_to_staging, generate_slsa_attestation, promote_release_oci,
    record_deployment_evidence, request_production_release, rollback_staging, run_staging_tests,
    staging_capabilities, staging_release_evidence, teardown_preview, trigger_release_ci,
)
from app.improvement_staging_store import list_production_release_requests, list_staging_deployments

router=APIRouter(prefix="/improvements/staging",tags=["improvement-staging"])


class CITriggerRequest(BaseModel):
    provider: str = Field(pattern="^(github_actions|gitlab_pipeline)$")
    ref: str = Field(min_length=1,max_length=200)
    workflow: str | None = Field(default=None,max_length=200)
    variables: dict[str,str] = Field(default_factory=dict)


class OCIPromotionRequest(BaseModel):
    source_ref: str = Field(min_length=1,max_length=500)
    destination_ref: str = Field(min_length=1,max_length=500)


class DeploymentRequest(BaseModel):
    provider: str = Field(default="external",pattern="^(external|kubernetes|ecs)$")
    image_ref: str | None = Field(default=None,max_length=500)
    namespace: str = Field(default="ai-staging",max_length=120)
    cluster: str | None = Field(default=None,max_length=200)
    service: str | None = Field(default=None,max_length=200)
    task_definition: str | None = Field(default=None,max_length=300)
    preview_url: str | None = Field(default=None,max_length=2000)


class DeploymentEvidenceRequest(BaseModel):
    status: str = Field(pattern="^(ready|failed|provisioning)$")
    deployment_ref: str | None = Field(default=None,max_length=1000)
    preview_url: str | None = Field(default=None,max_length=2000)
    evidence: dict[str,Any] = Field(default_factory=dict)


class StagingCheckSpec(BaseModel):
    kind: str = Field(default="smoke",pattern="^(smoke|api|e2e)$")
    args: list[str] = Field(min_length=1,max_length=30)
    cwd: str | None = Field(default=None,max_length=300)
    timeout_seconds: int | None = Field(default=None,ge=1,le=1800)


class StagingTestsRequest(BaseModel):
    checks: list[StagingCheckSpec] = Field(min_length=1,max_length=20)


class CosignRequest(BaseModel):
    image_ref: str = Field(min_length=1,max_length=500)


class ProductionReleaseRequestBody(BaseModel):
    confirm: bool = False
    notes: str | None = Field(default=None,max_length=2000)


def _operator(operator_id: str | None, token: str | None) -> dict[str,Any]:
    try: return verify_operator(operator_id,token)
    except ValueError as exc: raise HTTPException(status_code=401,detail=str(exc))


def _audit(operator: dict[str,Any], action: str, *, release_id: str | None = None, metadata: dict[str,Any] | None = None) -> None:
    project_name=None
    if release_id:
        release=get_release_candidate(release_id); project_name=(release or {}).get("project_name")
    record_operator_audit(operator=operator,action=action,project_name=project_name,schedule_id=None,
                          metadata={"release_id":release_id,**(metadata or {})})


def _public_deployment(item: dict[str,Any]) -> dict[str,Any]:
    out=dict(item); evidence=dict(out.get("evidence") or {}); evidence.pop("manifest_path_internal",None); out["evidence"]=evidence
    return out


@router.get("/capabilities")
def get_capabilities(): return staging_capabilities()


@router.post("/releases/{release_id}/ci/trigger")
def trigger_ci_route(release_id: str, body: CITriggerRequest,
                     x_improvement_operator_id: str | None=Header(default=None),
                     x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=trigger_release_ci(release_id,provider=body.provider,ref=body.ref,workflow=body.workflow,variables=body.variables)
    except KeyError: raise HTTPException(status_code=404,detail="Release not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"staging.ci.trigger",release_id=release_id,metadata={"provider":body.provider}); return result


@router.post("/releases/{release_id}/oci/promote")
def promote_oci_route(release_id: str, body: OCIPromotionRequest,
                      x_improvement_operator_id: str | None=Header(default=None),
                      x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=promote_release_oci(release_id,source_ref=body.source_ref,destination_ref=body.destination_ref)
    except KeyError: raise HTTPException(status_code=404,detail="Release not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"staging.oci.promote",release_id=release_id,metadata={"destination_ref":body.destination_ref}); return result


@router.post("/releases/{release_id}/deployments")
def deploy_route(release_id: str, body: DeploymentRequest,
                 x_improvement_operator_id: str | None=Header(default=None),
                 x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try:
        result=deploy_release_to_staging(release_id,provider=body.provider,image_ref=body.image_ref,namespace=body.namespace,
                                         cluster=body.cluster,service=body.service,task_definition=body.task_definition,preview_url=body.preview_url)
    except KeyError: raise HTTPException(status_code=404,detail="Release not found")
    except (ValueError,RuntimeError) as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"staging.deploy",release_id=release_id,metadata={"provider":body.provider,"deployment_id":result.get("id")}); return _public_deployment(result)


@router.get("/releases/{release_id}/deployments")
def get_deployments(release_id: str, limit: int=Query(default=100,ge=1,le=500)):
    if not get_release_candidate(release_id): raise HTTPException(status_code=404,detail="Release not found")
    return {"items":[_public_deployment(x) for x in list_staging_deployments(release_id=release_id,limit=limit)],"production_deployment_supported":False}


@router.post("/deployments/{deployment_id}/evidence")
def deployment_evidence_route(deployment_id: str, body: DeploymentEvidenceRequest,
                              x_improvement_operator_id: str | None=Header(default=None),
                              x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=record_deployment_evidence(deployment_id,status=body.status,deployment_ref=body.deployment_ref,preview_url=body.preview_url,evidence=body.evidence)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))
    record_operator_audit(operator=operator,action="staging.deployment.evidence",project_name=None,schedule_id=None,metadata={"deployment_id":deployment_id,"status":body.status}); return _public_deployment(result)


@router.post("/deployments/{deployment_id}/tests")
def staging_tests_route(deployment_id: str, body: StagingTestsRequest,
                        x_improvement_operator_id: str | None=Header(default=None),
                        x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=run_staging_tests(deployment_id,checks=[x.model_dump() for x in body.checks])
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    record_operator_audit(operator=operator,action="staging.tests",project_name=None,schedule_id=None,metadata={"deployment_id":deployment_id,"passed":result.get("passed")})
    if isinstance(result.get("deployment"),dict): result["deployment"]=_public_deployment(result["deployment"])
    return result


@router.post("/deployments/{deployment_id}/rollback")
def rollback_route(deployment_id: str,
                   x_improvement_operator_id: str | None=Header(default=None),
                   x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=rollback_staging(deployment_id)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except (ValueError,RuntimeError) as exc: raise HTTPException(status_code=409,detail=str(exc))
    record_operator_audit(operator=operator,action="staging.rollback",project_name=None,schedule_id=None,metadata={"deployment_id":deployment_id}); return _public_deployment(result)


@router.post("/previews/{preview_id}/teardown")
def teardown_preview_route(preview_id: str,
                           x_improvement_operator_id: str | None=Header(default=None),
                           x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=teardown_preview(preview_id)
    except KeyError: raise HTTPException(status_code=404,detail="Preview not found")
    record_operator_audit(operator=operator,action="staging.preview.teardown",project_name=None,schedule_id=None,metadata={"preview_id":preview_id}); return result


@router.post("/releases/{release_id}/attestations/slsa")
def slsa_route(release_id: str,
               x_improvement_operator_id: str | None=Header(default=None),
               x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=generate_slsa_attestation(release_id)
    except KeyError: raise HTTPException(status_code=404,detail="Release not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"staging.attestation.slsa",release_id=release_id,metadata={"attestation_id":result.get("id")}); return result


@router.post("/releases/{release_id}/attestations/cosign")
def cosign_route(release_id: str, body: CosignRequest,
                 x_improvement_operator_id: str | None=Header(default=None),
                 x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=attest_release_image(release_id,image_ref=body.image_ref)
    except KeyError: raise HTTPException(status_code=404,detail="Release not found")
    except (ValueError,RuntimeError) as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"staging.attestation.cosign",release_id=release_id,metadata={"status":result.get("status")}); return result


@router.get("/releases/{release_id}/evidence")
def staging_evidence_route(release_id: str):
    try:
        payload=staging_release_evidence(release_id)
        # Part 12 evidence contains internal workspace/artifact paths; strip them here too.
        if isinstance(payload.get("release"),dict):
            r=payload["release"].get("release") or {}; r.pop("workspace_path",None)
            for artifact in payload["release"].get("artifacts",[]): artifact.pop("path",None)
        payload["deployments"]=[_public_deployment(x) for x in payload.get("deployments",[])]
        return payload
    except KeyError: raise HTTPException(status_code=404,detail="Release not found")


@router.post("/releases/{release_id}/production-release-request")
def production_request_route(release_id: str, body: ProductionReleaseRequestBody,
                             x_improvement_operator_id: str | None=Header(default=None),
                             x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=request_production_release(release_id,operator=operator,confirm=body.confirm,notes=body.notes)
    except KeyError: raise HTTPException(status_code=404,detail="Release not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"release.production_request",release_id=release_id,metadata={"request_id":result["request"].get("id"),"production_deployment_executed":False}); return result


@router.get("/production-release-requests")
def get_production_requests(release_id: str | None=None, limit: int=Query(default=100,ge=1,le=500)):
    return {"items":list_production_release_requests(release_id=release_id,limit=limit),"production_deployment_supported":False}
