"""Bounded implementation planner.

The previous implementation used LangGraph for a two-node retry loop. This version
keeps the same public create_plan() contract without making the entire backend fail
to import when LangGraph is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from app.config import settings
from app.model_manager import model_manager, get_effective_model

logger = logging.getLogger(__name__)


def build_planner_prompt(user_request: str) -> str:
    return f"""You are an expert AI software architect and planner.
Break the request into safe, incremental implementation phases.
Do NOT output JSON. Output plain Markdown exactly in this shape:
Goal: [Brief goal]
Summary: [Brief summary]

# Phase 1: [Title]
Description: [What to do]

Rules:
- Maximum {settings.MAX_PLAN_PHASES} phases.
- One clear goal per phase.
- Prefer small verifiable changes.
- Do not include implementation code.

USER REQUEST:
{user_request}
"""


def extract_json(raw_text: str) -> str:
    lines = raw_text.splitlines()
    plan: Dict[str, Any] = {
        "goal": "Parsed Goal",
        "summary": "Parsed Summary",
        "recommended_stack": [],
        "phases": [],
        "risks": [],
        "next_phase_prompt": "Begin Phase 1",
    }
    current = None
    phase_id = 1
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("Goal:"):
            plan["goal"] = line.split(":", 1)[1].strip()
        elif line.startswith("Summary:"):
            plan["summary"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Phase"):
            if current:
                plan["phases"].append(current)
            title = line.split(":", 1)[1].strip() if ":" in line else line.replace("# Phase", "").strip()
            current = {
                "id": phase_id,
                "title": title,
                "description": "",
                "files_likely_needed": [],
                "dependencies": [phase_id - 1] if phase_id > 1 else [],
                "success_criteria": ["Phase behavior is machine-verified"],
                "allowed_actions": ["create_file", "modify_file", "read_file"],
                "forbidden_actions": ["delete_unrelated_files", "modify_protected_paths"],
            }
            phase_id += 1
        elif line.startswith("Description:") and current:
            current["description"] = line.split(":", 1)[1].strip()
    if current:
        plan["phases"].append(current)
    if not plan["phases"]:
        plan["phases"] = build_fallback_plan(plan["goal"])["phases"]
    plan["phases"] = plan["phases"][: int(settings.MAX_PLAN_PHASES)]
    return json.dumps(plan)


def build_fallback_plan(user_request: str) -> Dict[str, Any]:
    return {
        "goal": f"Safely implement: {user_request[:120]}",
        "summary": "Deterministic fallback plan because the planning model was unavailable or invalid.",
        "recommended_stack": [],
        "phases": [
            {
                "id": 1,
                "title": "Analyze and bound the change",
                "description": "Inspect relevant project files, existing tests, constraints, and likely impact before editing.",
                "files_likely_needed": [],
                "dependencies": [],
                "success_criteria": ["Relevant code and tests identified"],
                "allowed_actions": ["read_file"],
                "forbidden_actions": ["modify_file", "delete_unrelated_files"],
            },
            {
                "id": 2,
                "title": "Implement and verify",
                "description": "Create the smallest candidate patch and validate it in an isolated workspace.",
                "files_likely_needed": [],
                "dependencies": [1],
                "success_criteria": ["Targeted checks and protected regression checks pass"],
                "allowed_actions": ["create_file", "modify_file", "read_file"],
                "forbidden_actions": ["delete_unrelated_files", "modify_protected_paths"],
            },
        ],
        "risks": ["Fallback plan is generic and requires context collection before editing"],
        "next_phase_prompt": "Begin Phase 1: Analyze and bound the change.",
        "fallback_used": True,
    }


async def create_plan(user_request: str) -> Dict[str, Any]:
    """Create a plan with two bounded LLM attempts, then a deterministic fallback."""
    request = (user_request or "").strip()
    if not request:
        raise ValueError("Planning request cannot be empty")
    prompt = build_planner_prompt(request)
    errors = []
    for attempt in range(2):
        try:
            response = await model_manager.generate_completion(
                prompt=prompt,
                model=get_effective_model("planner"),
                temperature=0.2,
                max_tokens=3000,
                system_prompt="You are a careful software implementation planner.",
            )
            parsed = json.loads(extract_json(response))
            if parsed.get("phases"):
                parsed["planning_attempt"] = attempt + 1
                return parsed
            errors.append("planner returned no phases")
        except Exception as exc:
            logger.warning("Planner attempt %s failed: %s", attempt + 1, exc)
            errors.append(str(exc))
    fallback = build_fallback_plan(request)
    fallback["planner_errors"] = errors[-2:]
    return fallback
