from __future__ import annotations

from typing import Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.orchestrator import (
    abort_deployment, advance_external_stage, capabilities, create_authorized_deployment, deployment_detail,
    execute_deployment, observe_deployment, rollback_deployment, verify_handoff,
)
from app.security import verify_operator
from app.store import get_deployment, init_db, list_deployments
from app.hardening import capabilities as hardening_capabilities, chaos_simulation, concurrency_snapshot, evaluate_slo_window, migration_safety_check, rollback_drill, verify_audit_chain

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app=FastAPI(title="Independent Production Deployer",version="1.1.0",lifespan=lifespan)


class VerifyBody(BaseModel):
    package: dict[str,Any]
    authorization: dict[str,Any]

class CreateDeploymentBody(VerifyBody):
    provider: str = Field(pattern="^(kubernetes|ecs|external)$")
    target: dict[str,Any]
    confirm: bool = False

class ConfirmBody(BaseModel):
    confirm: bool = False

class ObservationBody(BaseModel):
    metrics: dict[str,Any]

class StageAdvanceBody(ObservationBody):
    action_status: str = Field(default="completed",pattern="^completed$")
    confirm: bool = False


def _operator(operator_id: str | None, token: str | None) -> dict[str,Any]:
    try: return verify_operator(operator_id,token)
    except ValueError as exc: raise HTTPException(status_code=401,detail=str(exc))




class SloWindowBody(BaseModel):
    min_samples: int | None = Field(default=None, ge=1, le=500)
    pass_ratio: float | None = Field(default=None, ge=0.0, le=1.0)

class ChaosBody(BaseModel):
    scenario: str


@app.get("/hardening/capabilities")
def hardening_caps(): return hardening_capabilities()

@app.get("/hardening/migration-safety")
def hardening_migration(): return migration_safety_check()

@app.get("/hardening/concurrency")
def hardening_concurrency(): return concurrency_snapshot()

@app.post("/hardening/chaos/simulate")
def hardening_chaos(body: ChaosBody):
    try: return chaos_simulation(scenario=body.scenario)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))

@app.get("/deployments/{deployment_id}/audit-chain")
def deployment_audit_chain(deployment_id: str):
    try: return verify_audit_chain(deployment_id)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")

@app.post("/deployments/{deployment_id}/slo-window")
def deployment_slo_window(deployment_id: str, body: SloWindowBody):
    try: return evaluate_slo_window(deployment_id,min_samples=body.min_samples,pass_ratio=body.pass_ratio)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")

@app.get("/deployments/{deployment_id}/rollback-drill")
def deployment_rollback_drill(deployment_id: str):
    try: return rollback_drill(deployment_id)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")

@app.get("/health/live")
def live(): return {"status":"ok","service":"independent-production-deployer"}

@app.get("/health/ready")
def ready():
    init_db()
    blockers=[]
    if not settings.PRODUCTION_DEPLOYER_PACKAGE_SIGNING_KEY: blockers.append("package_signing_key_not_configured")
    if not settings.PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY: blockers.append("receipt_signing_key_not_configured")
    if str(settings.PRODUCTION_DEPLOYER_OPERATOR_CREDENTIALS_JSON or "{}") in {"","{}"}: blockers.append("operator_registry_not_configured")
    return {"status":"ready" if not blockers else "not_ready","blockers":blockers,"execution_enabled":bool(settings.PRODUCTION_DEPLOYER_EXECUTION_ENABLED)}

@app.get("/capabilities")
def caps(): return capabilities()

@app.post("/packages/verify")
def verify(body: VerifyBody): return verify_handoff(body.package,body.authorization)

@app.post("/deployments")
def create(body: CreateDeploymentBody, x_production_operator_id: str | None=Header(default=None), x_production_operator_token: str | None=Header(default=None)):
    operator=_operator(x_production_operator_id,x_production_operator_token)
    try: return create_authorized_deployment(package=body.package,authorization=body.authorization,provider=body.provider,target=body.target,operator=operator,confirm=body.confirm)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))

@app.get("/deployments")
def deployments(project_name: str | None=None,limit: int=Query(default=100,ge=1,le=500)): return {"items":list_deployments(project_name=project_name,limit=limit)}

@app.get("/deployments/{deployment_id}")
def detail(deployment_id: str):
    try: return deployment_detail(deployment_id)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")

@app.post("/deployments/{deployment_id}/execute")
def execute(deployment_id: str,body: ConfirmBody,x_production_operator_id: str | None=Header(default=None),x_production_operator_token: str | None=Header(default=None)):
    operator=_operator(x_production_operator_id,x_production_operator_token)
    try: return execute_deployment(deployment_id,operator=operator,confirm=body.confirm)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))

@app.post("/deployments/{deployment_id}/observations")
def observe(deployment_id: str,body: ObservationBody,x_production_operator_id: str | None=Header(default=None),x_production_operator_token: str | None=Header(default=None)):
    operator=_operator(x_production_operator_id,x_production_operator_token)
    try: return observe_deployment(deployment_id,metrics=body.metrics,operator=operator)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))

@app.post("/deployments/{deployment_id}/stages/advance")
def advance(deployment_id: str,body: StageAdvanceBody,x_production_operator_id: str | None=Header(default=None),x_production_operator_token: str | None=Header(default=None)):
    operator=_operator(x_production_operator_id,x_production_operator_token)
    try: return advance_external_stage(deployment_id,metrics=body.metrics,action_status=body.action_status,operator=operator,confirm=body.confirm)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))

@app.post("/deployments/{deployment_id}/rollback")
def rollback(deployment_id: str,body: ConfirmBody,x_production_operator_id: str | None=Header(default=None),x_production_operator_token: str | None=Header(default=None)):
    operator=_operator(x_production_operator_id,x_production_operator_token)
    try: return rollback_deployment(deployment_id,operator=operator,confirm=body.confirm)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))

@app.post("/deployments/{deployment_id}/abort")
def abort(deployment_id: str,body: ConfirmBody,x_production_operator_id: str | None=Header(default=None),x_production_operator_token: str | None=Header(default=None)):
    operator=_operator(x_production_operator_id,x_production_operator_token)
    try: return abort_deployment(deployment_id,operator=operator,confirm=body.confirm)
    except KeyError: raise HTTPException(status_code=404,detail="Deployment not found")
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))

@app.get("/deployments/{deployment_id}/receipt")
def receipt(deployment_id: str):
    item=get_deployment(deployment_id)
    if not item: raise HTTPException(status_code=404,detail="Deployment not found")
    if not item.get("receipt"): raise HTTPException(status_code=409,detail="Deployment does not have a terminal receipt yet")
    return item["receipt"]
