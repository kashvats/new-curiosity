"""IDE mode orchestration over the shared agent/repair services."""
from __future__ import annotations

import json
from typing import Any, Dict

from app.agent_runtime import AgentContext, agent_registry
from app.config import settings
from app.context_builder import build_ide_context, render_context_for_llm
from app.ide_store import append_ide_event, update_ide_session
from app.model_manager import get_effective_model, model_manager
from app.planner import create_plan
from app.repair_loop import RepairIssue, repair_issue
from app.security_review import review_security

WRITE_MODES = {"edit", "fix", "agent"}
READ_MODES = {"ask", "plan", "review"}
SUPPORTED_MODES = READ_MODES | WRITE_MODES


def _event_sink(session_id: str):
    def sink(event_type: str, payload: Dict[str, Any]) -> None:
        append_ide_event(
            session_id,
            event_type,
            stage=event_type,
            message=_event_message(event_type, payload),
            payload=payload,
        )
    return sink


def _event_message(event_type: str, payload: Dict[str, Any]) -> str:
    messages = {
        "repair_started": "Repair loop started",
        "candidate_workspace_ready": "Isolated candidate workspace ready",
        "attempt_started": f"Repair attempt {payload.get('attempt_no', '')} started".strip(),
        "diagnosis_ready": "Debugger produced a diagnosis",
        "candidate_drafted": "Coder produced a candidate patch",
        "validation_started": "Machine validation started",
        "validation_finished": "Machine validation passed" if payload.get("passed") else "Machine validation failed",
        "review_finished": "Independent review completed",
        "security_finished": "Security review completed",
        "quality_finished": "Quality scoring completed",
        "repair_verified": "Candidate passed all gates and awaits approval",
        "attempt_failed": "Attempt failed; evidence will feed the next attempt",
        "repair_stopped": "Repair loop stopped",
    }
    return messages.get(event_type, event_type.replace("_", " ").title())


def _context_summary(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "requested_files": context.get("requested_files", []),
        "context_files": [item.get("path") for item in context.get("files", [])],
        "diagnostic_count": len(context.get("diagnostics", [])),
        "has_terminal_output": bool(context.get("terminal_output")),
        "has_git_diff": bool((context.get("git") or {}).get("diff")),
        "test_discovery": context.get("test_discovery", {}),
    }


async def run_ide_session(session_id: str, request: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(request.get("mode", "ask")).lower().strip()
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported IDE mode '{mode}'")

    update_ide_session(session_id, status="running", mark_started=True)
    append_ide_event(session_id, "session_started", stage="context", message=f"{mode} session started")

    try:
        context = build_ide_context(
            project_name=request.get("project_name", "default"),
            files=request.get("files") or [],
            current_file=request.get("current_file"),
            selected_text=request.get("selected_text", ""),
            diagnostics=request.get("diagnostics") or [],
            terminal_output=request.get("terminal_output", ""),
        )
        summary = _context_summary(context)
        append_ide_event(session_id, "context_ready", stage="context", message="Project context collected", payload=summary)
        rendered = render_context_for_llm(context)
        task = str(request.get("task", "")).strip()
        if not task:
            raise ValueError("IDE task cannot be empty")

        if mode == "ask":
            append_ide_event(session_id, "llm_started", stage="ask", message="Asking project-aware model")
            prompt = (
                "You are the Ask-mode coding assistant. Answer the user's question using the supplied project evidence. "
                "Do not claim to have changed files or run commands. If evidence is insufficient, say what is missing.\n\n"
                f"QUESTION:\n{task}\n\nPROJECT CONTEXT:\n{rendered}"
            )
            answer = await model_manager.generate_completion(
                prompt, model=get_effective_model("planner"), temperature=0.2, max_tokens=4000
            )
            result = {"mode": mode, "answer": answer, "context": summary}

        elif mode == "plan":
            append_ide_event(session_id, "planning_started", stage="plan", message="Creating implementation plan")
            plan = await create_plan(f"{task}\n\nRelevant project context:\n{rendered[:30000]}")
            result = {"mode": mode, "plan": plan, "context": summary}

        elif mode == "review":
            changes = [
                {"action": "inspect", "path": item.get("path", ""), "content": item.get("content", "")}
                for item in context.get("files", [])
            ]
            review = await agent_registry.run("reviewer", AgentContext(
                task=task,
                project_name=request.get("project_name", "default"),
                project_root=context["project_root"],
                files=context.get("requested_files", []),
                evidence={"changes": changes, "validation": {"editor_diagnostics": context.get("diagnostics", []), "git": context.get("git", {})}},
            ))
            security = review_security(changes)
            result = {"mode": mode, "review": review.data, "security": security, "context": summary}
            append_ide_event(session_id, "review_finished", stage="review", message="Review completed", payload={"review": review.data, "security": security})

        else:
            plan = None
            if mode == "agent":
                append_ide_event(session_id, "planning_started", stage="plan", message="Agent is planning before editing")
                plan = await create_plan(f"{task}\n\nRelevant project context:\n{rendered[:26000]}")
                append_ide_event(session_id, "plan_ready", stage="plan", message="Agent plan ready", payload={"plan": plan})

            evidence = dict(request.get("evidence") or {})
            evidence.update({
                "editor_diagnostics": context.get("diagnostics", []),
                "terminal_output": context.get("terminal_output", ""),
                "git": context.get("git", {}),
                "ide_mode": mode,
            })
            if plan is not None:
                evidence["implementation_plan"] = plan

            validation_plan = request.get("validation_plan") or (context.get("test_discovery") or {}).get("quick_checks", [])
            issue = RepairIssue(
                task=task,
                project_name=request.get("project_name", "default"),
                files=context.get("requested_files", []),
                evidence=evidence,
                validation_plan=validation_plan,
            )
            update_ide_session(session_id, issue_id=issue.issue_id)
            requested_attempts = request.get("max_attempts")
            if mode == "edit" and requested_attempts is None:
                requested_attempts = min(2, int(settings.MAX_REPAIR_ATTEMPTS))
            repair = await repair_issue(issue, requested_attempts, event_sink=_event_sink(session_id))
            result = {"mode": mode, "repair": repair, "plan": plan, "context": summary}

        status = "verified" if result.get("repair", {}).get("status") == "verified" else "completed"
        if result.get("repair", {}).get("status") == "needs_human":
            status = "needs_human"
        update_ide_session(session_id, status=status, result=result, mark_completed=True)
        append_ide_event(session_id, "session_completed", stage="done", message=f"Session finished with status {status}", payload={"status": status})
        return result
    except Exception as exc:
        update_ide_session(session_id, status="failed", error=str(exc), mark_completed=True)
        append_ide_event(session_id, "session_failed", stage="failed", message=str(exc), payload={"error": str(exc)})
        raise
