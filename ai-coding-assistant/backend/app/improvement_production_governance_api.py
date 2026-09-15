"""FastAPI surface for Part 14 production release governance.

No route in this router performs a production deployment.
"""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.improvement_scheduler_security import record_operator_audit, verify_operator
from app.improvement_production_governance import (
    assign_release_train, attach_artifact_binding, attach_change_ticket, build_deployment_package, create_case_from_request,
    create_train, evaluate_case, freeze_status, generate_rollout_plan, governance_case_detail,
    issue_deployment_authorization, lock_case, production_governance_capabilities, submit_approval, update_train_status, verify_deployment_authorization, verify_deployment_package,
)
from app.improvement_production_governance_store import (
    get_deployment_authorization, get_deployment_package, get_governance_case, get_release_train, list_deployment_authorizations, list_deployment_packages,
    list_governance_approvals, list_governance_cases, list_governance_events, list_release_trains,
)

router=APIRouter(prefix="/improvements/production-governance",tags=["production-governance"])

class CreateCaseBody(BaseModel):
    production_request_id: str = Field(min_length=1,max_length=200)

class ChangeTicketBody(BaseModel):
    system: str = Field(default="jira",max_length=40)
    reference: str = Field(min_length=2,max_length=120)
    url: str | None = Field(default=None,max_length=2000)

class RolloutPlanBody(BaseModel):
    strategy: str = Field(pattern="^(canary|blue_green|rolling)$")

class ArtifactBindingBody(BaseModel):
    artifact_ref: str = Field(min_length=1,max_length=2000)
    digest_sha256: str = Field(min_length=64,max_length=71)
    kind: str = Field(default="oci_image",pattern="^(oci_image|ecs_task_definition|generic_immutable_artifact)$")

class ApprovalBody(BaseModel):
    decision: str = Field(default="approve",pattern="^(approve|reject)$")
    comment: str | None = Field(default=None,max_length=2000)

class ConfirmBody(BaseModel):
    confirm: bool = False

class ReleaseTrainBody(BaseModel):
    name: str = Field(min_length=1,max_length=200)
    window_start: str = Field(min_length=1,max_length=80)
    window_end: str = Field(min_length=1,max_length=80)
    timezone: str = Field(default="UTC",min_length=1,max_length=80)
    metadata: dict[str,Any] = Field(default_factory=dict)

class AssignTrainBody(BaseModel):
    release_train_id: str = Field(min_length=1,max_length=200)

class TrainStatusBody(BaseModel):
    status: str = Field(pattern="^(open|frozen|closed)$")


def _operator(operator_id: str | None, token: str | None) -> dict[str,Any]:
    try: return verify_operator(operator_id,token)
    except ValueError as exc: raise HTTPException(status_code=401,detail=str(exc))


def _audit(operator: dict[str,Any], action: str, *, case_id: str | None = None, metadata: dict[str,Any] | None = None) -> None:
    project_name=None
    if case_id:
        case=get_governance_case(case_id); project_name=(case or {}).get("project_name")
    record_operator_audit(operator=operator,action=action,project_name=project_name,schedule_id=None,
                          metadata={"case_id":case_id,**(metadata or {})})

@router.get("/capabilities")
def capabilities_route(): return production_governance_capabilities()

@router.get("/freeze-status")
def freeze_status_route(at: str | None = Query(default=None,max_length=80)): return freeze_status(at=at)

@router.post("/cases")
def create_case_route(body: CreateCaseBody, x_improvement_operator_id: str | None=Header(default=None),
                      x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=create_case_from_request(body.production_request_id,operator=operator)
    except KeyError: raise HTTPException(status_code=404,detail="Production release request not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"production_governance.case.create",case_id=result["id"]); return result

@router.get("/cases")
def cases_route(project_name: str | None=None,status: str | None=None,limit: int=Query(default=100,ge=1,le=500)):
    return {"items":list_governance_cases(project_name=project_name,status=status,limit=limit),"production_deployment_supported":False}

@router.get("/cases/{case_id}")
def case_detail_route(case_id: str):
    try: return governance_case_detail(case_id)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")

@router.post("/cases/{case_id}/change-ticket")
def change_ticket_route(case_id: str, body: ChangeTicketBody, x_improvement_operator_id: str | None=Header(default=None),
                        x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=attach_change_ticket(case_id,system=body.system,reference=body.reference,url=body.url,operator=operator)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"production_governance.change_ticket",case_id=case_id,metadata={"reference":body.reference}); return result

@router.post("/cases/{case_id}/artifact-binding")
def artifact_binding_route(case_id: str, body: ArtifactBindingBody, x_improvement_operator_id: str | None=Header(default=None),
                           x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=attach_artifact_binding(case_id,artifact_ref=body.artifact_ref,digest_sha256=body.digest_sha256,kind=body.kind,operator=operator)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"production_governance.artifact_binding",case_id=case_id,metadata={"kind":body.kind,"artifact_ref":body.artifact_ref}); return result


@router.post("/cases/{case_id}/rollout-plan")
def rollout_plan_route(case_id: str, body: RolloutPlanBody, x_improvement_operator_id: str | None=Header(default=None),
                       x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=generate_rollout_plan(case_id,strategy=body.strategy,operator=operator)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"production_governance.rollout_plan",case_id=case_id,metadata={"strategy":body.strategy}); return result

@router.post("/cases/{case_id}/approvals")
def approval_route(case_id: str, body: ApprovalBody, x_improvement_operator_id: str | None=Header(default=None),
                   x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=submit_approval(case_id,operator=operator,decision=body.decision,comment=body.comment)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,f"production_governance.approval.{body.decision}",case_id=case_id,metadata={"approval_id":result["id"]}); return result

@router.get("/cases/{case_id}/approvals")
def approvals_route(case_id: str,limit: int=Query(default=200,ge=1,le=500)):
    if not get_governance_case(case_id): raise HTTPException(status_code=404,detail="Governance case not found")
    return {"items":list_governance_approvals(case_id,limit=limit)}

@router.get("/cases/{case_id}/events")
def events_route(case_id: str,limit: int=Query(default=200,ge=1,le=500)):
    if not get_governance_case(case_id): raise HTTPException(status_code=404,detail="Governance case not found")
    return {"items":list_governance_events(case_id,limit=limit)}

@router.post("/cases/{case_id}/evaluate")
def evaluate_route(case_id: str):
    try: return evaluate_case(case_id,update_status=True)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")

@router.post("/cases/{case_id}/lock")
def lock_route(case_id: str, body: ConfirmBody, x_improvement_operator_id: str | None=Header(default=None),
               x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=lock_case(case_id,operator=operator,confirm=body.confirm)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"production_governance.case.lock",case_id=case_id); return result

@router.post("/cases/{case_id}/deployment-package")
def package_route(case_id: str, body: ConfirmBody, x_improvement_operator_id: str | None=Header(default=None),
                  x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=build_deployment_package(case_id,operator=operator,confirm=body.confirm)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"production_governance.package.create",case_id=case_id,metadata={"package_id":result["package"]["id"]}); return result

@router.get("/packages")
def packages_route(case_id: str | None=None,limit: int=Query(default=100,ge=1,le=500)):
    return {"items":list_deployment_packages(case_id=case_id,limit=limit),"production_credentials_included":False,"production_deployment_supported":False}

@router.get("/packages/{package_id}")
def package_detail_route(package_id: str):
    item=get_deployment_package(package_id)
    if not item: raise HTTPException(status_code=404,detail="Deployment package not found")
    return {"package":item,"production_credentials_included":False,"production_deployment_supported":False}

@router.get("/packages/{package_id}/verify")
def package_verify_route(package_id: str):
    try: return verify_deployment_package(package_id)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment package or governance case not found")


@router.post("/packages/{package_id}/deployment-authorization")
def package_authorization_route(package_id: str, body: ConfirmBody, x_improvement_operator_id: str | None=Header(default=None),
                                x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=issue_deployment_authorization(package_id,operator=operator,confirm=body.confirm)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment package not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    package=get_deployment_package(package_id) or {}
    _audit(operator,"production_governance.deployment_authorization",case_id=package.get("case_id"),metadata={"package_id":package_id,"authorization_id":result["authorization"]["id"]})
    return result


@router.get("/deployment-authorizations")
def authorizations_route(package_id: str | None=None,limit: int=Query(default=100,ge=1,le=500)):
    return {"items":list_deployment_authorizations(package_id=package_id,limit=limit),"production_credentials_included":False}


@router.get("/deployment-authorizations/{authorization_id}")
def authorization_detail_route(authorization_id: str):
    item=get_deployment_authorization(authorization_id)
    if not item: raise HTTPException(status_code=404,detail="Deployment authorization not found")
    try: verification=verify_deployment_authorization(authorization_id)
    except Exception: verification={"valid":False}
    return {"authorization":item,"verification":verification,"production_credentials_included":False}


@router.post("/release-trains")
def create_train_route(body: ReleaseTrainBody, x_improvement_operator_id: str | None=Header(default=None),
                       x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=create_train(name=body.name,window_start=body.window_start,window_end=body.window_end,timezone_name=body.timezone,operator=operator,metadata=body.metadata)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    record_operator_audit(operator=operator,action="production_governance.release_train.create",project_name=None,schedule_id=None,metadata={"release_train_id":result["id"]}); return result

@router.get("/release-trains")
def list_trains_route(status: str | None=None,limit: int=Query(default=100,ge=1,le=500)):
    return {"items":list_release_trains(status=status,limit=limit)}

@router.post("/release-trains/{train_id}/status")
def train_status_route(train_id: str, body: TrainStatusBody, x_improvement_operator_id: str | None=Header(default=None),
                       x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=update_train_status(train_id,status=body.status,operator=operator)
    except KeyError: raise HTTPException(status_code=404,detail="Release train not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    record_operator_audit(operator=operator,action="production_governance.release_train.status",project_name=None,schedule_id=None,metadata={"release_train_id":train_id,"status":body.status}); return result

@router.post("/cases/{case_id}/release-train")
def assign_train_route(case_id: str, body: AssignTrainBody, x_improvement_operator_id: str | None=Header(default=None),
                       x_improvement_operator_token: str | None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: result=assign_release_train(case_id,body.release_train_id,operator=operator)
    except KeyError: raise HTTPException(status_code=404,detail="Governance case or release train not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    _audit(operator,"production_governance.release_train.assign",case_id=case_id,metadata={"release_train_id":body.release_train_id}); return result
