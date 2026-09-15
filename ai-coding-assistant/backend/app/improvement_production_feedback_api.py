"""API for signed production deployment receipts and production-learning visibility."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.improvement_production_feedback import (
    ingest_production_outcome, list_production_outcomes, production_feedback_capabilities,
    production_learning_summary,
)

router = APIRouter(prefix="/improvements/production-outcomes", tags=["production-outcomes"])


class ProductionOutcomeBody(BaseModel):
    payload: dict[str, Any]
    digest_sha256: str = Field(min_length=64, max_length=64)
    signature: str = Field(min_length=32, max_length=256)


@router.get("/capabilities")
def capabilities_route():
    return production_feedback_capabilities()


@router.post("")
def ingest_route(body: ProductionOutcomeBody):
    try:
        return ingest_production_outcome(payload=body.payload, digest_sha256=body.digest_sha256, signature=body.signature)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("")
def list_route(project_name: str | None = None, limit: int = Query(default=100, ge=1, le=500)):
    return {"items": list_production_outcomes(project_name=project_name, limit=limit), "backend_can_execute_production": False}


@router.get("/learning")
def learning_route(project_name: str = Query(min_length=1, max_length=200)):
    return production_learning_summary(project_name)
