"""Cycle-level resource budgeting for controlled improvement experiments."""
from __future__ import annotations

from typing import Any, Dict

from app.config import settings


def resolve_cycle_budget(request: Dict[str, Any] | None = None) -> Dict[str, int]:
    request = request or {}
    return {
        "max_candidate_repairs": max(1, min(int(request.get("max_candidate_repairs") or settings.IMPROVEMENT_MAX_CYCLE_REPAIRS), int(settings.IMPROVEMENT_MAX_CYCLE_REPAIRS))),
        "max_attempts": max(1, min(int(request.get("max_cycle_attempts") or settings.IMPROVEMENT_MAX_CYCLE_ATTEMPTS), int(settings.IMPROVEMENT_MAX_CYCLE_ATTEMPTS))),
        "max_changed_files": max(1, min(int(request.get("max_changed_files") or settings.IMPROVEMENT_MAX_CYCLE_CHANGED_FILES), int(settings.IMPROVEMENT_MAX_CYCLE_CHANGED_FILES))),
        "max_patch_bytes": max(1024, min(int(request.get("max_patch_bytes") or settings.IMPROVEMENT_MAX_CYCLE_PATCH_BYTES), int(settings.IMPROVEMENT_MAX_CYCLE_PATCH_BYTES))),
    }


def empty_usage() -> Dict[str, int]:
    return {"candidate_repairs": 0, "attempts": 0, "changed_files": 0, "patch_bytes": 0}


def repair_usage(repair: Dict[str, Any]) -> Dict[str, int]:
    changes = repair.get("proposed_changes") or []
    patch_bytes = 0
    for change in changes:
        content = change.get("content")
        if isinstance(content, str):
            patch_bytes += len(content.encode("utf-8"))
    return {
        "candidate_repairs": 1,
        "attempts": len(repair.get("attempts") or []),
        "changed_files": len({str(change.get("path")) for change in changes if change.get("path")}),
        "patch_bytes": patch_bytes,
    }


def add_usage(current: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, int]:
    return {key: int(current.get(key, 0)) + int(delta.get(key, 0)) for key in empty_usage()}


def budget_violations(usage: Dict[str, Any], budget: Dict[str, Any]) -> list[str]:
    checks = {
        "candidate_repairs": "max_candidate_repairs",
        "attempts": "max_attempts",
        "changed_files": "max_changed_files",
        "patch_bytes": "max_patch_bytes",
    }
    return [f"{key}>{limit_key}" for key, limit_key in checks.items() if int(usage.get(key, 0)) > int(budget.get(limit_key, 0))]
