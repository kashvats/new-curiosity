"""High-level phased orchestration built on the shared bounded repair engine."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from app.apply_changes import apply_drafted_changes
from app.config import settings
from app.planner import create_plan
from app.project_paths import resolve_project_root
from app.repair_loop import RepairIssue, repair_issue
from app.adaptive_orchestration import route_task, deterministic_single_phase_plan

logger = logging.getLogger(__name__)


async def run_orchestrator(
    idea: str,
    context_files: List[str] | None = None,
    *,
    project_name: str = "default",
    auto_apply: bool = False,
) -> Dict[str, Any]:
    """Plan work and verify every phase before any live write.

    auto_apply defaults to False. When enabled, only candidates that pass machine
    validation + reviewer + security + quality gates are applied using the shared
    snapshot-backed apply service.
    """
    context_files = list(context_files or [])
    try:
        project_root = resolve_project_root(project_name)
    except ValueError as exc:
        return {"status": "error", "message": str(exc), "log": []}

    route = route_task(idea, files=context_files)
    if getattr(settings, "V11_ADAPTIVE_ROUTING_ENABLED", True) and not route.needs_planner:
        plan = deterministic_single_phase_plan(idea, route)
    else:
        plan = await create_plan(idea)
        plan.setdefault("adaptive_route", route.to_dict())
        plan.setdefault("planner_skipped", False)
    phases = plan.get("phases", [])
    if not phases:
        return {"status": "error", "message": "Planner returned no phases", "plan": plan, "log": []}

    # Keep planning artifacts inside the selected project, not at an unrelated workspace root.
    try:
        (project_root / "raw_prompt.md").write_text(f"# Original Request\n\n{idea}\n", encoding="utf-8")
        lines = ["# Implementation Plan", "", f"Goal: {plan.get('goal', '')}", f"Summary: {plan.get('summary', '')}", ""]
        for phase in phases:
            lines.extend([f"## Phase {phase.get('id')}: {phase.get('title')}", str(phase.get("description", "")), ""])
        (project_root / "plan.md").write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist planning artifacts: %s", exc)

    log: List[Dict[str, Any]] = []
    for idx, phase in enumerate(phases):
        phase_id = phase.get("id", idx + 1)
        title = phase.get("title", f"Phase {phase_id}")
        task = f"Phase: {title}\nDescription: {phase.get('description', '')}\nOverall goal: {idea}"
        files = phase.get("files_likely_needed") or context_files
        result = await repair_issue(RepairIssue(task=task, project_name=project_name, files=files))
        row: Dict[str, Any] = {
            "phase_id": phase_id,
            "title": title,
            "verification_status": result.get("status"),
            "attempt_count": len(result.get("attempts", [])),
            "quality": result.get("quality"),
        }
        if result.get("status") != "verified":
            row["status"] = "blocked"
            row["reason"] = result.get("reason") or result.get("status")
            log.append(row)
            return {"status": "blocked", "idea": idea, "plan": plan, "log": log, "requires_human": True}

        if auto_apply:
            applied = apply_drafted_changes(result.get("proposed_changes", []), project_root)
            row["status"] = "applied"
            row["apply_results"] = applied
        else:
            row["status"] = "verified_waiting_approval"
            row["proposed_changes"] = result.get("proposed_changes", [])
        log.append(row)
        if not auto_apply:
            # Manual mode stops after one verified phase so a human can inspect the diff.
            break

    return {
        "status": "success" if auto_apply else "waiting_approval",
        "idea": idea,
        "plan": plan,
        "log": log,
        "auto_apply": auto_apply,
        "adaptive_route": route.to_dict(),
    }
