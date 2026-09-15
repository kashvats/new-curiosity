"""Bounded detect -> diagnose -> code -> verify -> retry repair engine.

v1.1 adds deterministic adaptive routing, repository-aware context selection and
contextual experience retrieval.  Verification/reviewer/security/quality gates are
unchanged and remain mandatory for a verified candidate.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

from app.adaptive_orchestration import route_task
from app.agent_runtime import AgentContext, agent_registry
from app.candidate_workspace import CandidateWorkspace
from app.config import settings
from app.experience_memory import record_experience, search_experiences, format_experiences_for_prompt
from app.model_manager import get_effective_model
from app.patch_engine import apply_changes, preview_changes, PatchError
from app.repair_attempt_store import store_repair_attempt, update_repair_attempt_result
from app.repository_intelligence import rank_relevant_files
from app.verification_service import verification_service
from app.project_paths import resolve_project_root
from app.quality_scorer import score_candidate
from app.verified_candidate_store import store_verified_repair
from app.test_discovery import discover_project_checks


@dataclass
class RepairIssue:
    task: str
    project_name: str
    files: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    validation_plan: List[Dict[str, Any]] = field(default_factory=list)
    cycle_id: str | None = None
    issue_id: str = field(default_factory=lambda: str(uuid.uuid4()))


def _project_root(project_name: str) -> Path:
    return resolve_project_root(project_name)


def _normalize_change_paths(changes: List[Dict[str, Any]], project_name: str) -> List[Dict[str, Any]]:
    normalized = []
    prefix = project_name.rstrip("/\\") + "/" if project_name and project_name not in {".", "default"} else ""
    for change in changes:
        item = dict(change)
        path = str(item.get("path", "")).replace("\\", "/")
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        item["path"] = path
        normalized.append(item)
    return normalized


def _default_validation_plan(project_root: Path) -> List[Dict[str, Any]]:
    return discover_project_checks(project_root).get("quick_checks", [])


def _materialize_candidate_changes(source_root: Path, candidate_root: Path) -> List[Dict[str, Any]]:
    """Return complete create/modify changes needed to transform source into candidate."""
    import hashlib
    changes: List[Dict[str, Any]] = []
    ignored_parts = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "venv", ".venv", "dist", "build", ".next"}
    for candidate_file in sorted(p for p in candidate_root.rglob("*") if p.is_file()):
        rel = candidate_file.relative_to(candidate_root)
        if any(part in ignored_parts for part in rel.parts):
            continue
        source_file = source_root / rel
        candidate_bytes = candidate_file.read_bytes()
        try:
            candidate_text = candidate_bytes.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if source_file.exists() and source_file.is_file():
            source_bytes = source_file.read_bytes()
            if source_bytes == candidate_bytes:
                continue
            try:
                source_text = source_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            changes.append({
                "action": "modify",
                "path": rel.as_posix(),
                "content": candidate_text,
                "reason": "Cumulative verified repair result",
                "expected_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            })
        else:
            changes.append({
                "action": "create",
                "path": rel.as_posix(),
                "content": candidate_text,
                "reason": "Cumulative verified repair result",
                "expected_sha256": None,
            })
    return changes


def _same_failure_seen(attempts: List[Dict[str, Any]], signature: str) -> bool:
    return bool(signature) and sum(1 for item in attempts if item.get("failure_signature") == signature) >= 2


def _emit(event_sink: Callable[[str, Dict[str, Any]], None] | None, event_type: str, payload: Dict[str, Any] | None = None) -> None:
    if not event_sink:
        return
    try:
        event_sink(event_type, payload or {})
    except Exception:
        # Observability must never make a repair fail.
        pass


def _record_attempt_experience(
    issue: RepairIssue,
    *,
    strategy: str,
    outcome: str,
    files: List[str],
    validation: Dict[str, Any],
    attempt_no: int,
    diagnosis_source: str,
    lesson: str = "",
) -> None:
    if not getattr(settings, "V11_EXPERIENCE_MEMORY_ENABLED", True):
        return
    try:
        record_experience(
            project_name=issue.project_name,
            issue_id=issue.issue_id,
            task=issue.task,
            strategy=strategy,
            outcome=outcome,
            files=files,
            failure_class=None if outcome == "succeeded" else str(validation.get("status") or "validation_failed"),
            validation_status=str(validation.get("status") or outcome),
            lesson=(lesson or str(validation.get("message") or validation.get("status") or outcome))[:1500],
            metadata={"attempt_no": attempt_no, "diagnosis_source": diagnosis_source},
        )
    except Exception:
        # Memory is advisory and must not affect repair correctness.
        pass


async def repair_issue(
    issue: RepairIssue,
    max_attempts: int | None = None,
    event_sink: Callable[[str, Dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    source_root = _project_root(issue.project_name)
    max_attempts = min(int(max_attempts or settings.MAX_REPAIR_ATTEMPTS), int(settings.MAX_REPAIR_ATTEMPTS))
    attempts: List[Dict[str, Any]] = []

    route = route_task(issue.task, files=issue.files, evidence=issue.evidence)
    working_files = list(issue.files)
    repository_selection: Dict[str, Any] = {}
    if getattr(settings, "V11_REPOSITORY_CONTEXT_ENABLED", True) and route.expand_repository_context:
        try:
            repository_selection = rank_relevant_files(
                source_root,
                issue.task,
                seed_files=working_files,
                limit=route.context_file_budget,
            )
            for rel in repository_selection.get("selected_paths", []):
                if rel not in working_files and len(working_files) < route.context_file_budget:
                    working_files.append(rel)
        except Exception:
            repository_selection = {}

    prior_experiences: List[Dict[str, Any]] = []
    if getattr(settings, "V11_EXPERIENCE_MEMORY_ENABLED", True):
        try:
            prior_experiences = search_experiences(
                project_name=issue.project_name,
                task=issue.task,
                files=working_files,
                limit=int(getattr(settings, "V11_EXPERIENCE_PROMPT_LIMIT", 5)),
            )
        except Exception:
            prior_experiences = []

    production_strategy_stats: Dict[str, Dict[str, Any]] = {}
    try:
        from app.improvement_production_feedback import production_learning_statistics
        production_strategy_stats = {
            str(item.get("strategy_key")): item
            for item in production_learning_statistics(project_name=issue.project_name)
            if item.get("strategy_key")
        }
    except Exception:
        production_strategy_stats = {}

    _emit(event_sink, "repair_started", {
        "issue_id": issue.issue_id,
        "project_name": issue.project_name,
        "task": issue.task,
        "adaptive_route": route.to_dict(),
        "working_files": working_files,
        "prior_experience_count": len(prior_experiences),
    })

    with CandidateWorkspace.create(source_root) as candidate:
        _emit(event_sink, "candidate_workspace_ready", {"issue_id": issue.issue_id})
        for attempt_no in range(1, max_attempts + 1):
            _emit(event_sink, "attempt_started", {"attempt_no": attempt_no, "max_attempts": max_attempts})
            failure_evidence = attempts[-1].get("validation_result", {}) if attempts else issue.evidence

            # v1.1: direct first attempt for bounded non-debug work.  Any retry
            # automatically escalates to the debugger, preserving diagnosis when it is
            # actually useful instead of paying for it unconditionally.
            use_debugger = (
                attempt_no > 1
                or route.needs_initial_debugger
                or not getattr(settings, "V11_ADAPTIVE_ROUTING_ENABLED", True)
            )
            if use_debugger:
                debug_result = await agent_registry.run("debugger", AgentContext(
                    task=issue.task,
                    project_name=issue.project_name,
                    project_root=str(candidate.root),
                    files=working_files,
                    evidence=failure_evidence,
                    previous_attempts=attempts,
                ))
                diagnosis = debug_result.data.get("diagnosis", "")
                strategy = debug_result.data.get("next_strategy", "") or route.default_strategy
                diagnosis_source = "debugger"
            else:
                diagnosis = (
                    "Adaptive router selected a direct bounded coding attempt. "
                    "Machine validation will escalate any failure to the debugger."
                )
                strategy = route.default_strategy
                diagnosis_source = "adaptive_router"

            _emit(event_sink, "diagnosis_ready", {
                "attempt_no": attempt_no,
                "diagnosis": diagnosis,
                "strategy": strategy,
                "source": diagnosis_source,
                "debugger_invoked": use_debugger,
            })

            history = json.dumps(attempts[-3:], default=str, ensure_ascii=False)
            experience_context = format_experiences_for_prompt(prior_experiences)
            production_context = ""
            prod = production_strategy_stats.get(strategy)
            if prod:
                production_context = f"\n\nPRODUCTION HISTORY FOR THIS STRATEGY:\n{json.dumps(prod, ensure_ascii=False)}"

            extra_context = (
                f"DIAGNOSIS SOURCE: {diagnosis_source}\n"
                f"DIAGNOSIS:\n{diagnosis}\nNEXT STRATEGY:\n{strategy}\n\n"
                f"PREVIOUS ATTEMPTS (do not repeat ineffective fixes):\n{history}\n\n"
                f"{experience_context}{production_context}"
            )

            from app.coder import draft_code_changes
            coder = await draft_code_changes(
                task=issue.task,
                file_paths=working_files,
                extra_context=extra_context,
                project_name=issue.project_name,
                project_root=str(candidate.root),
                expand_context=False,
            )
            _emit(event_sink, "candidate_drafted", {
                "attempt_no": attempt_no,
                "status": coder.get("status", "ok"),
                "change_count": len(coder.get("proposed_changes", [])),
                "summary": coder.get("summary", ""),
            })
            if coder.get("status") == "error":
                validation = {"passed": False, "status": "coder_error", "message": coder.get("message", "Unknown coder error")}
                changes: List[Dict[str, Any]] = []
                plan: List[Dict[str, Any]] = []
            else:
                changes = _normalize_change_paths(coder.get("proposed_changes", []), issue.project_name)
                plan = coder.get("validation_plan") or issue.validation_plan or _default_validation_plan(candidate.root)
                try:
                    preview = [r.to_dict() for r in preview_changes(candidate.root, changes)]
                    apply_changes(candidate.root, changes)
                    discovered = discover_project_checks(candidate.root, [c.get("path", "") for c in changes])
                    regression_plan = discovered.get("regression_checks", [])
                    _emit(event_sink, "validation_started", {"attempt_no": attempt_no, "checks": plan, "regression_checks": regression_plan})
                    validation = verification_service.verify_with_regression(str(candidate.root), plan, regression_plan)
                    validation["diff_preview"] = preview
                    validation["discovered_checks"] = discovered
                    _emit(event_sink, "validation_finished", {
                        "attempt_no": attempt_no,
                        "passed": validation.get("passed"),
                        "status": validation.get("status"),
                        "checks": validation.get("checks", []),
                    })
                except (PatchError, ValueError) as exc:
                    validation = {"passed": False, "status": "patch_blocked", "message": str(exc)}

            persisted = store_repair_attempt(
                issue_id=issue.issue_id,
                cycle_id=issue.cycle_id,
                attempt_no=attempt_no,
                model=coder.get("model", get_effective_model("coder")),
                diagnosis=diagnosis,
                changes=changes,
                validation_plan=plan,
                validation_result=validation,
            )
            attempt_record = {
                "attempt_no": attempt_no,
                "diagnosis": diagnosis,
                "strategy": strategy,
                "diagnosis_source": diagnosis_source,
                "debugger_invoked": use_debugger,
                "changes": changes,
                "validation_plan": plan,
                "validation_result": validation,
                **persisted,
            }
            attempts.append(attempt_record)

            if not validation.get("passed"):
                _record_attempt_experience(
                    issue,
                    strategy=strategy,
                    outcome="failed",
                    files=[c.get("path", "") for c in changes] or working_files,
                    validation=validation,
                    attempt_no=attempt_no,
                    diagnosis_source=diagnosis_source,
                )

            if validation.get("passed"):
                final_changes = _materialize_candidate_changes(source_root, candidate.root)
                review = await agent_registry.run("reviewer", AgentContext(
                    task=issue.task,
                    project_name=issue.project_name,
                    project_root=str(candidate.root),
                    evidence={"changes": final_changes, "validation": validation},
                ))
                security = await agent_registry.run("security", AgentContext(
                    task=issue.task,
                    project_name=issue.project_name,
                    project_root=str(candidate.root),
                    evidence={"changes": final_changes, "validation": validation},
                ))
                quality = score_candidate(
                    validation=validation,
                    review=review.data,
                    security=security.data,
                    changes=final_changes,
                )
                _emit(event_sink, "review_finished", {"attempt_no": attempt_no, **review.data})
                _emit(event_sink, "security_finished", {"attempt_no": attempt_no, **security.data})
                _emit(event_sink, "quality_finished", {"attempt_no": attempt_no, **quality})

                if quality.get("accepted"):
                    validation["review"] = review.data
                    validation["security"] = security.data
                    validation["quality"] = quality
                    update_repair_attempt_result(persisted["id"], validation, quality.get("score"))
                    attempt_record["validation_result"] = validation
                    attempt_record["quality_score"] = quality.get("score")
                    store_verified_repair(
                        issue_id=issue.issue_id,
                        project_name=issue.project_name,
                        task=issue.task,
                        proposed_changes=final_changes,
                        validation=validation,
                        review=review.data,
                        security=security.data,
                        quality=quality,
                    )
                    _record_attempt_experience(
                        issue,
                        strategy=strategy,
                        outcome="succeeded",
                        files=[c.get("path", "") for c in final_changes],
                        validation={"status": "verified", "passed": True},
                        attempt_no=attempt_no,
                        diagnosis_source=diagnosis_source,
                        lesson=str(coder.get("summary") or diagnosis or "Verified repair succeeded"),
                    )
                    _emit(event_sink, "repair_verified", {
                        "issue_id": issue.issue_id,
                        "attempt_no": attempt_no,
                        "quality": quality,
                        "change_count": len(final_changes),
                    })
                    return {
                        "status": "verified",
                        "issue_id": issue.issue_id,
                        "attempts": attempts,
                        "proposed_changes": final_changes,
                        "validation": validation,
                        "review": review.data,
                        "security": security.data,
                        "quality": quality,
                        "requires_approval": True,
                        "adaptive_route": route.to_dict(),
                        "working_files": working_files,
                        "repository_selection": repository_selection,
                        "prior_experiences": prior_experiences,
                        "note": "Candidate was isolated and cleaned after verification; proposed_changes contains the cumulative verified result.",
                    }

                validation = dict(validation)
                validation.update({
                    "passed": False,
                    "status": "gate_failed",
                    "message": "Candidate failed reviewer/security/quality gate",
                    "review": review.data,
                    "security": security.data,
                    "quality": quality,
                })
                persisted = update_repair_attempt_result(persisted["id"], validation, quality.get("score"))
                attempt_record["validation_result"] = validation
                attempt_record["quality_score"] = quality.get("score")
                attempt_record["failure_signature"] = persisted.get("failure_signature", "")
                _record_attempt_experience(
                    issue,
                    strategy=strategy,
                    outcome="gate_failed",
                    files=[c.get("path", "") for c in final_changes],
                    validation=validation,
                    attempt_no=attempt_no,
                    diagnosis_source=diagnosis_source,
                )

            signature = attempt_record.get("failure_signature") or persisted.get("failure_signature", "")
            _emit(event_sink, "attempt_failed", {
                "attempt_no": attempt_no,
                "failure_signature": signature,
                "validation": attempt_record.get("validation_result", {}),
            })
            if _same_failure_seen(attempts, signature):
                _emit(event_sink, "repair_stopped", {"issue_id": issue.issue_id, "reason": "repeated_failure"})
                return {
                    "status": "needs_human",
                    "reason": "repeated_failure",
                    "issue_id": issue.issue_id,
                    "attempts": attempts,
                    "adaptive_route": route.to_dict(),
                    "working_files": working_files,
                }

        _emit(event_sink, "repair_stopped", {"issue_id": issue.issue_id, "reason": "max_retries_reached"})
        return {
            "status": "needs_human",
            "reason": "max_retries_reached",
            "issue_id": issue.issue_id,
            "attempts": attempts,
            "adaptive_route": route.to_dict(),
            "working_files": working_files,
        }
