from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.improvement_certification import capabilities, evaluate_readiness, issue_certificate, list_certificates, list_evidence, record_evidence, verify_certificate
from app.improvement_scheduler_security import verify_operator

router=APIRouter(prefix="/improvements/certification",tags=["production-certification"])

class EvidenceBody(BaseModel):
    project_name: str = Field(min_length=1,max_length=200)
    gate: str = Field(min_length=1,max_length=120)
    passed: bool
    details: dict[str,Any] = Field(default_factory=dict)
    source: str = Field(default="manual-verified",min_length=1,max_length=120)

class CertificateBody(BaseModel):
    project_name: str = Field(min_length=1,max_length=200)
    confirm: bool=False

def _operator(operator_id: str|None,token: str|None):
    try: return verify_operator(operator_id,token)
    except ValueError as exc: raise HTTPException(status_code=401,detail=str(exc))

@router.get("/capabilities")
def get_capabilities(): return capabilities()

@router.post("/evidence")
def post_evidence(body: EvidenceBody,x_improvement_operator_id: str|None=Header(default=None),x_improvement_operator_token: str|None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: return record_evidence(project_name=body.project_name,gate=body.gate,passed=body.passed,details=body.details,source=body.source,operator=operator)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))

@router.get("/evidence")
def get_evidence(project_name: str,limit:int=Query(default=200,ge=1,le=1000)): return {"items":list_evidence(project_name=project_name,limit=limit)}

@router.get("/readiness")
def readiness(project_name: str): return evaluate_readiness(project_name)

@router.post("/certificates")
def create_certificate(body: CertificateBody,x_improvement_operator_id: str|None=Header(default=None),x_improvement_operator_token: str|None=Header(default=None)):
    operator=_operator(x_improvement_operator_id,x_improvement_operator_token)
    try: return issue_certificate(project_name=body.project_name,operator=operator,confirm=body.confirm)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))

@router.get("/certificates")
def certificates(project_name: str|None=None,limit:int=Query(default=100,ge=1,le=500)): return {"items":list_certificates(project_name=project_name,limit=limit)}

@router.get("/certificates/{certificate_id}/verify")
def verify(certificate_id: str):
    try: return verify_certificate(certificate_id)
    except KeyError: raise HTTPException(status_code=404,detail="Certificate not found")
