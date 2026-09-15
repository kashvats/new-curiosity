"""User-triggered self-improvement controller with Part 5 learning/experiments.

The controller remains intentionally non-autonomous: there is no recurring scheduler
and no verified repair can write to the live project without explicit confirm=true.
Part 5 adds outcome-aware ranking, manual candidate selection, bounded side-by-side
experiments, drift/dependency evidence, and cycle-level resource budgets.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from app.agent_runtime import AgentContext, agent_registry
from app.config import settings
from app.improvement_brain import select_improvement_candidate
from app.candidate_suppression import apply_repeat_suppression
from app.improvement_governance import evaluate_verified_candidate_governance, store_governance_check
from app.improvement_policy import candidate_allowed_by_policy, resolved_improvement_policy
from app.improvement_test_impact import enrich_candidates_with_test_impact, store_test_impact
from app.improvement_budget import add_usage, budget_violations, empty_usage, repair_usage, resolve_cycle_budget
from app.improvement_learning import apply_outcome_learning
from app.improvement_approvals import approval_requirement_status
from app.improvement_integrity import seal_policy_snapshot, verify_policy_snapshot
from app.improvement_regression_attribution import store_regression_attribution
from app.improvement_risk_controls import apply_failure_cooldowns_and_risk
from app.improvement_store import (
    append_improvement_event,
    get_improvement_candidate,
    get_improvement_cycle,
    list_improvement_candidates,
    list_improvement_experiments,
    store_health_snapshot,
    store_improvement_candidates,
    store_improvement_experiment,
    store_improvement_outcome,
    update_improvement_candidate,
    update_improvement_cycle,
    update_improvement_experiment_status,
)
from app.project_health import capture_project_health
from app.repair_loop import RepairIssue, repair_issue
from app.verified_candidate_store import apply_verified_repair, discard_verified_repair, get_verified_repair, rollback_applied_repair

_ALLOWED_POLICIES = {"manual", "observe_only"}
_PAUSED_OR_TERMINAL_STATES = {
    "WAITING_SELECTION", "WAITING_APPROVAL", "VALIDATION_FAILED",
    "BLOCKED_BY_CAPABILITY", "BUDGET_EXCEEDED", "ROLLBACK_REQUIRED", "GOVERNANCE_BLOCKED", "POLICY_INTEGRITY_BLOCKED", "APPROVAL_BLOCKED", "CANCELLED",
}


def _transition(cycle_id: str, state: str, message: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    cycle = update_improvement_cycle(cycle_id, state=state)
    append_improvement_event(cycle_id, "state_changed", state=state, message=message, payload=payload or {})
    return cycle


def _safe_policy(value: str | None) -> str:
    policy = (value or settings.IMPROVEMENT_DEFAULT_POLICY).strip().lower()
    if policy not in _ALLOWED_POLICIES:
        raise ValueError(f"Unsupported improvement policy '{policy}'. Supported policies are manual and observe_only.")
    return policy


def _eligible_candidates(candidates: Iterable[Dict[str, Any]], request: Dict[str, Any], project_policy: Dict[str, Any] | None = None) -> list[Dict[str, Any]]:
    policy = project_policy or {}
    policy_risks = {str(v).strip().lower() for v in (policy.get("allowed_risks") or str(settings.IMPROVEMENT_ALLOWED_RISKS).split(",")) if str(v).strip()}
    request_risks = {str(v).strip().lower() for v in (request.get("allowed_risks") or policy_risks) if str(v).strip()}
    allowed = policy_risks & request_risks if policy_risks else request_risks
    policy_threshold = float(policy.get("min_priority") if policy.get("min_priority") is not None else settings.IMPROVEMENT_MIN_PRIORITY)
    request_threshold = float(settings.IMPROVEMENT_MIN_PRIORITY if request.get("min_priority") is None else request.get("min_priority"))
    threshold = max(policy_threshold, request_threshold)
    output: list[Dict[str, Any]] = []
    for item in candidates:
        if str(item.get("risk") or "medium").lower() not in allowed:
            continue
        if float(item.get("priority_score") or 0.0) < threshold:
            continue
        permitted, _reason = candidate_allowed_by_policy(item, policy) if policy else (not bool(item.get("suppressed")), None)
        if permitted:
            output.append(item)
    output.sort(key=lambda item: (-float(item.get("priority_score") or 0.0), float(item.get("estimated_cost") or 1.0), str(item.get("id"))))
    return output


def _cycle_policy(cycle: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = cycle.get("policy_snapshot") or {}
    if snapshot.get("policy"):
        return snapshot["policy"]
    return resolved_improvement_policy(cycle["project_name"])["policy"]


def _cancel_if_requested(cycle_id: str, *, message: str = "Improvement cycle cancelled by user") -> Dict[str, Any] | None:
    cycle = get_improvement_cycle(cycle_id)
    if not cycle or not cycle.get("cancel_requested"):
        return None
    if cycle.get("completed_at") and cycle.get("state") == "CANCELLED":
        return cycle
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    result = {"status": "cancelled", "reason": "cancelled_by_user"}
    update_improvement_cycle(
        cycle_id, state="CANCELLED", result=result, stop_reason="cancelled_by_user",
        cancelled_at=now, mark_completed=True,
    )
    append_improvement_event(cycle_id, "cycle_cancelled", state="CANCELLED", message=message)
    return get_improvement_cycle(cycle_id) or result


def _ensure_budget(cycle_id: str, request: Dict[str, Any]) -> tuple[Dict[str, int], Dict[str, int]]:
    cycle = get_improvement_cycle(cycle_id) or {}
    budget = cycle.get("budget") or resolve_cycle_budget(request)
    usage = {**empty_usage(), **(cycle.get("usage") or {})}
    if not cycle.get("budget") or not cycle.get("usage"):
        update_improvement_cycle(cycle_id, budget=budget, usage=usage)
    return budget, usage


def _mark_budget_exceeded(cycle_id: str, *, budget: Dict[str, Any], usage: Dict[str, Any], violations: list[str]) -> Dict[str, Any]:
    result = {"status": "budget_exceeded", "budget": budget, "usage": usage, "violations": violations}
    update_improvement_cycle(
        cycle_id, state="BUDGET_EXCEEDED", result=result, stop_reason=",".join(violations), usage=usage, mark_completed=True,
    )
    append_improvement_event(
        cycle_id, "cycle_stopped", state="BUDGET_EXCEEDED",
        message="Improvement cycle resource budget was exceeded", payload=result,
    )
    return get_improvement_cycle(cycle_id) or result


async def _repair_one_candidate(
    cycle_id: str,
    candidate: Dict[str, Any],
    *,
    project_name: str,
    request: Dict[str, Any],
    budget: Dict[str, int],
    usage: Dict[str, int],
    experiment_rank: int,
    persist_experiment: bool,
) -> tuple[Dict[str, Any], Dict[str, int], str]:
    remaining_repairs = int(budget["max_candidate_repairs"]) - int(usage.get("candidate_repairs", 0))
    remaining_attempts = int(budget["max_attempts"]) - int(usage.get("attempts", 0))
    if remaining_repairs <= 0 or remaining_attempts <= 0:
        raise RuntimeError("cycle_resource_budget_exhausted")

    requested_attempts = int(request.get("max_attempts") or settings.MAX_REPAIR_ATTEMPTS)
    effective_attempts = max(1, min(requested_attempts, int(settings.MAX_REPAIR_ATTEMPTS), remaining_attempts))

    def repair_event(event_type: str, payload: Dict[str, Any]) -> None:
        append_improvement_event(
            cycle_id,
            f"repair.{event_type}",
            state="VALIDATING",
            message=str(payload.get("message") or event_type.replace("_", " ")),
            payload={"candidate_id": candidate["id"], "experiment_rank": experiment_rank, **payload},
        )

    issue = RepairIssue(
        task=candidate["proposal"],
        project_name=project_name,
        files=list(candidate.get("likely_files") or []),
        evidence={
            **(candidate.get("evidence") or {}),
            "improvement_candidate": {
                "id": candidate["id"], "problem": candidate["problem"], "risk": candidate["risk"],
                "priority_score": candidate["priority_score"], "strategy_key": candidate.get("strategy_key"),
                "history_samples": candidate.get("history_samples", 0),
                "history_success_rate": candidate.get("history_success_rate", 0.0),
            },
            "experiment": {"rank": experiment_rank, "enabled": persist_experiment},
        },
        validation_plan=list(candidate.get("validation_plan") or []),
        cycle_id=cycle_id,
    )
    repair = await repair_issue(issue, effective_attempts, event_sink=repair_event)
    delta = repair_usage(repair)
    next_usage = add_usage(usage, delta)
    update_improvement_candidate(candidate["id"], issue_id=issue.issue_id)
    update_improvement_cycle(cycle_id, usage=next_usage)

    quality_score = None
    if isinstance(repair.get("quality"), dict) and repair["quality"].get("score") is not None:
        quality_score = float(repair["quality"]["score"])
    status = "verified" if repair.get("status") == "verified" else str(repair.get("status") or "failed")

    if persist_experiment:
        store_improvement_experiment(
            cycle_id=cycle_id, candidate_id=candidate["id"], issue_id=issue.issue_id,
            experiment_rank=experiment_rank, status=status, quality_score=quality_score,
            usage=delta,
            result={
                "status": repair.get("status"), "reason": repair.get("reason"),
                "quality": repair.get("quality", {}), "validation": repair.get("validation", {}),
                "proposed_change_count": len(repair.get("proposed_changes") or []),
            },
        )

    return repair, next_usage, issue.issue_id


async def _validate_selected_candidates(
    cycle_id: str,
    selected_candidate_id: str,
    *,
    experiment_mode: bool | None = None,
    experiment_candidates: int | None = None,
) -> Dict[str, Any]:
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise KeyError(cycle_id)
    request = cycle.get("request") or {}
    project_name = cycle["project_name"]
    project_policy = _cycle_policy(cycle)
    cancelled = _cancel_if_requested(cycle_id)
    if cancelled:
        return cancelled
    candidates = list_improvement_candidates(cycle_id)
    eligible = _eligible_candidates(candidates, request, project_policy)
    selected = next((item for item in eligible if item["id"] == selected_candidate_id), None)
    if not selected:
        raise ValueError("Selected candidate does not belong to this cycle or does not pass current risk/priority policy")

    use_experiments = bool(request.get("experiment_mode", False) if experiment_mode is None else experiment_mode)
    max_experiments = int(experiment_candidates or request.get("experiment_candidates") or 2)
    max_experiments = max(1, min(max_experiments, int(settings.IMPROVEMENT_EXPERIMENT_MAX_CANDIDATES)))
    pool = [selected]
    if use_experiments:
        pool.extend(item for item in eligible if item["id"] != selected["id"])
        pool = pool[:max_experiments]

    budget, usage = _ensure_budget(cycle_id, request)
    if int(usage.get("candidate_repairs", 0)) >= int(budget["max_candidate_repairs"]):
        return _mark_budget_exceeded(cycle_id, budget=budget, usage=usage, violations=["candidate_repairs>max_candidate_repairs"])

    _transition(
        cycle_id, "VALIDATING",
        f"Preparing {len(pool)} isolated improvement candidate(s)" if use_experiments else "Preparing the selected improvement in an isolated candidate workspace",
        payload={"candidate_ids": [item["id"] for item in pool], "experiment_mode": use_experiments},
    )
    verified: list[Dict[str, Any]] = []

    for rank, candidate in enumerate(pool, start=1):
        cancelled = _cancel_if_requested(cycle_id)
        if cancelled:
            return cancelled
        update_improvement_candidate(candidate["id"], status="experimenting" if use_experiments else "selected")
        append_improvement_event(
            cycle_id, "candidate_validation_started", state="VALIDATING", message=candidate["problem"],
            payload={"candidate_id": candidate["id"], "rank": rank, "experiment_mode": use_experiments},
        )
        try:
            repair, usage, issue_id = await _repair_one_candidate(
                cycle_id, candidate, project_name=project_name, request=request, budget=budget, usage=usage,
                experiment_rank=rank, persist_experiment=use_experiments,
            )
        except RuntimeError as exc:
            if str(exc) == "cycle_resource_budget_exhausted":
                return _mark_budget_exceeded(cycle_id, budget=budget, usage=usage, violations=["repair_or_attempt_budget_exhausted"])
            raise

        violations = budget_violations(usage, budget)
        if violations:
            update_improvement_candidate(candidate["id"], status="budget_exceeded", issue_id=issue_id)
            return _mark_budget_exceeded(cycle_id, budget=budget, usage=usage, violations=violations)

        validation = repair.get("validation") if isinstance(repair.get("validation"), dict) else {}
        quality_score = (repair.get("quality") or {}).get("score") if isinstance(repair.get("quality"), dict) else None
        store_test_impact(
            cycle_id=cycle_id, candidate_id=candidate["id"], issue_id=issue_id, project_name=project_name,
            changed_files=[row.get("path", "") for row in (repair.get("proposed_changes") or [])],
            validation=validation, quality_score=float(quality_score) if quality_score is not None else None,
        )

        current_cycle = get_improvement_cycle(cycle_id) or {}
        if current_cycle.get("cancel_requested"):
            if repair.get("status") == "verified":
                try:
                    discard_verified_repair(issue_id, reason="Improvement cycle cancelled while candidate validation was in flight")
                except (KeyError, ValueError):
                    pass
            cancelled = _cancel_if_requested(cycle_id, message="Improvement cycle cancelled after the in-flight candidate finished validation")
            if cancelled:
                return cancelled

        if repair.get("status") == "verified":
            governance = evaluate_verified_candidate_governance(
                project_name, repair.get("proposed_changes") or [], policy_snapshot=cycle.get("policy_snapshot") or None,
            )
            stored_governance = store_governance_check(
                cycle_id=cycle_id, candidate_id=candidate["id"], issue_id=issue_id, project_name=project_name, result=governance,
            )
            append_improvement_event(
                cycle_id, "governance_checked", state="VALIDATING",
                message=f"Candidate governance: {governance.get('status')}",
                payload={"candidate_id": candidate["id"], "issue_id": issue_id, "governance_check_id": stored_governance["id"],
                         "violations": governance.get("violations", []), "warnings": governance.get("warnings", [])},
            )
            if not governance.get("passed"):
                update_improvement_candidate(candidate["id"], status="governance_blocked", issue_id=issue_id)
                try:
                    discard_verified_repair(issue_id, reason="Blocked by Part 6 improvement governance")
                except (KeyError, ValueError):
                    pass
                if use_experiments:
                    update_improvement_experiment_status(
                        cycle_id, candidate["id"], status="governance_blocked",
                        result_patch={"governance": governance},
                    )
                continue
            if use_experiments and governance.get("warnings"):
                update_improvement_experiment_status(cycle_id, candidate["id"], status="verified", result_patch={"governance": governance})
            update_improvement_candidate(candidate["id"], status="experiment_verified" if use_experiments else "verified", issue_id=issue_id)
            verified.append({
                "candidate": get_improvement_candidate(candidate["id"]) or candidate,
                "repair": repair, "issue_id": issue_id, "governance": governance,
            })
        else:
            update_improvement_candidate(candidate["id"], status="validation_failed", issue_id=issue_id)

    if not verified:
        result = {
            "status": "needs_human", "reason": "no_experiment_candidate_verified" if use_experiments else "validation_failed",
            "experiments": list_improvement_experiments(cycle_id) if use_experiments else [], "budget": budget, "usage": usage,
        }
        update_improvement_cycle(
            cycle_id, state="VALIDATION_FAILED", result=result, stop_reason=result["reason"], usage=usage, mark_completed=True,
        )
        append_improvement_event(cycle_id, "cycle_stopped", state="VALIDATION_FAILED", message="No candidate could be verified", payload=result)
        return get_improvement_cycle(cycle_id) or result

    cancelled = _cancel_if_requested(cycle_id)
    if cancelled:
        return cancelled

    # Prefer machine/reviewer quality, then learned priority. This lets experiments
    # compare independent isolated repairs without changing the live workspace.
    verified.sort(key=lambda item: (
        -float((item["repair"].get("quality") or {}).get("score") or 0.0),
        -float(item["candidate"].get("priority_score") or 0.0),
    ))
    winner = verified[0]
    winner_candidate = winner["candidate"]
    winner_issue = winner["issue_id"]
    for item in verified[1:]:
        update_improvement_candidate(item["candidate"]["id"], status="discarded", issue_id=item["issue_id"])
        try:
            discard_verified_repair(item["issue_id"], reason="Non-winning Part 6 experiment candidate discarded")
        except (KeyError, ValueError):
            pass
        if use_experiments:
            update_improvement_experiment_status(cycle_id, item["candidate"]["id"], status="discarded", result_patch={"discard_reason": "non_winner"})
    update_improvement_candidate(winner_candidate["id"], status="verified", issue_id=winner_issue)
    update_improvement_cycle(cycle_id, selected_candidate_id=winner_candidate["id"], selected_issue_id=winner_issue, usage=usage)
    append_improvement_event(
        cycle_id, "candidate_selected", state="VALIDATING", message=winner_candidate["problem"],
        payload={
            "candidate_id": winner_candidate["id"], "issue_id": winner_issue,
            "priority_score": winner_candidate.get("priority_score"),
            "quality_score": (winner["repair"].get("quality") or {}).get("score"),
            "selected_from_experiment": use_experiments,
        },
    )

    baseline_row = None
    if cycle.get("baseline_snapshot_id"):
        from app.improvement_store import get_health_snapshot
        baseline_row = get_health_snapshot(cycle["baseline_snapshot_id"])
    result = {
        "status": "waiting_approval",
        "baseline": baseline_row,
        "selected_candidate": get_improvement_candidate(winner_candidate["id"]) or winner_candidate,
        "verified_repair": winner["repair"],
        "governance": winner.get("governance", {}),
        "experiments": list_improvement_experiments(cycle_id) if use_experiments else [],
        "budget": budget, "usage": usage,
        "requires_approval": True,
    }
    update_improvement_cycle(cycle_id, state="WAITING_APPROVAL", result=result, usage=usage)
    append_improvement_event(
        cycle_id, "approval_required", state="WAITING_APPROVAL",
        message="Verified improvement is ready; explicit approval is required before live writes",
        payload={"issue_id": winner_issue, "candidate_id": winner_candidate["id"], "experiment_mode": use_experiments},
    )
    return get_improvement_cycle(cycle_id) or result


async def run_improvement_cycle(cycle_id: str) -> Dict[str, Any]:
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise KeyError(cycle_id)
    request = cycle.get("request") or {}
    policy = _safe_policy(cycle.get("policy"))
    project_name = cycle["project_name"]

    if cycle.get("state") not in {"IDLE"} or cycle.get("completed_at"):
        return cycle
    cancelled = _cancel_if_requested(cycle_id)
    if cancelled:
        return cancelled
    policy_snapshot = cycle.get("policy_snapshot") or resolved_improvement_policy(project_name)
    policy_integrity = cycle.get("policy_integrity") or seal_policy_snapshot(policy_snapshot)
    if not cycle.get("policy_snapshot") or not cycle.get("policy_integrity"):
        update_improvement_cycle(cycle_id, policy_snapshot=policy_snapshot, policy_integrity=policy_integrity)
        cycle = get_improvement_cycle(cycle_id) or cycle
    integrity_status = verify_policy_snapshot(policy_snapshot, policy_integrity)
    if not integrity_status.get("passed"):
        result = {"status": "policy_integrity_blocked", "integrity": integrity_status}
        update_improvement_cycle(cycle_id, state="POLICY_INTEGRITY_BLOCKED", result=result, stop_reason=integrity_status.get("reason"), mark_completed=True)
        append_improvement_event(cycle_id, "cycle_stopped", state="POLICY_INTEGRITY_BLOCKED", message="Policy snapshot integrity verification failed", payload=result)
        return get_improvement_cycle(cycle_id) or result
    project_policy = policy_snapshot.get("policy") or {}

    try:
        budget, usage = _ensure_budget(cycle_id, request)
        _transition(cycle_id, "OBSERVING", "Capturing baseline project health")
        baseline = capture_project_health(project_name, run_checks=bool(request.get("run_checks", True)))
        baseline_row = store_health_snapshot(project_name=project_name, snapshot=baseline, cycle_id=cycle_id, phase="baseline")
        update_improvement_cycle(
            cycle_id,
            baseline_score=float(baseline.get("health_score") or 0.0),
            baseline_snapshot_id=baseline_row["id"], budget=budget, usage=usage,
        )
        append_improvement_event(
            cycle_id, "health_captured", state="OBSERVING", message=f"Baseline health {baseline.get('health_score')}",
            payload={"snapshot_id": baseline_row["id"], "health_score": baseline.get("health_score"), "dimensions": baseline.get("dimensions", {})},
        )
        cancelled = _cancel_if_requested(cycle_id)
        if cancelled:
            return cancelled

        threshold = float(request.get("acceptable_health_score", settings.IMPROVEMENT_ACCEPTABLE_HEALTH_SCORE))
        if not request.get("force", False) and float(baseline.get("health_score") or 0.0) >= threshold and not baseline.get("findings"):
            result = {"status": "no_action", "reason": "health_acceptable", "baseline": baseline_row, "candidates": []}
            update_improvement_cycle(cycle_id, state="IDLE", result=result, stop_reason="health_acceptable", mark_completed=True)
            append_improvement_event(cycle_id, "cycle_stopped", state="IDLE", message="Health already acceptable", payload={"threshold": threshold})
            return get_improvement_cycle(cycle_id) or result

        _transition(cycle_id, "DIAGNOSING", "Converting health evidence into improvement opportunities")
        _transition(cycle_id, "PROPOSING", "Generating and prioritizing bounded improvement candidates")
        agent_result = await agent_registry.run("improvement", AgentContext(
            task="Generate small, evidence-backed improvement candidates",
            project_name=project_name,
            evidence={"health_snapshot": baseline, "cycle_id": cycle_id},
        ))
        generated = list(agent_result.data.get("candidates") or [])
        learned = apply_outcome_learning(project_name, generated)
        with_impact = enrich_candidates_with_test_impact(project_name, learned)
        repetition = project_policy.get("repetition") or {}
        guarded = apply_repeat_suppression(
            project_name, with_impact,
            enabled=bool(repetition.get("enabled", True)),
            repeat_limit=int(repetition.get("repeat_limit") or settings.IMPROVEMENT_REPEAT_LIMIT),
            history_limit=int(repetition.get("history_limit") or settings.IMPROVEMENT_REPEAT_HISTORY_LIMIT),
        )
        risk_controlled = apply_failure_cooldowns_and_risk(project_name, guarded)
        cancelled = _cancel_if_requested(cycle_id)
        if cancelled:
            return cancelled
        persisted = store_improvement_candidates(cycle_id, risk_controlled)
        append_improvement_event(
            cycle_id, "candidates_ready", state="PROPOSING", message=f"Generated {len(persisted)} candidate(s)",
            payload={
                "candidate_ids": [item["id"] for item in persisted],
                "learning_applied": any(int(item.get("history_samples") or 0) >= int(settings.IMPROVEMENT_MIN_LEARNING_SAMPLES) for item in persisted),
                "suppressed_candidate_ids": [item["id"] for item in persisted if item.get("suppressed")],
                "cooldown_candidate_ids": [item["id"] for item in persisted if item.get("cooldown_until")],
                "risk_escalated_candidate_ids": [item["id"] for item in persisted if (item.get("risk_escalation") or {}).get("escalated")],
                "impact_memory_candidates": sum(1 for item in persisted if (item.get("impact_memory") or {}).get("samples")),
                "policy_id": policy_snapshot.get("policy_id"),
                "policy_version": policy_snapshot.get("version", 0),
            },
        )

        eligible = _eligible_candidates(persisted, request, project_policy)
        selected = eligible[0] if eligible else None
        if not selected:
            result = {"status": "no_action", "reason": "no_eligible_candidate", "baseline": baseline_row, "candidates": persisted}
            update_improvement_cycle(cycle_id, state="IDLE", result=result, stop_reason="no_eligible_candidate", mark_completed=True)
            append_improvement_event(cycle_id, "cycle_stopped", state="IDLE", message="No candidate passed risk/priority policy")
            return get_improvement_cycle(cycle_id) or result

        if policy == "observe_only":
            update_improvement_candidate(selected["id"], status="selected")
            update_improvement_cycle(cycle_id, selected_candidate_id=selected["id"])
            result = {"status": "observe_only", "selected_candidate": selected, "baseline": baseline_row, "candidates": list_improvement_candidates(cycle_id)}
            update_improvement_cycle(cycle_id, state="IDLE", result=result, stop_reason="observe_only", mark_completed=True)
            append_improvement_event(cycle_id, "cycle_stopped", state="IDLE", message="Observe-only policy: no repair was generated")
            return get_improvement_cycle(cycle_id) or result

        if bool(request.get("pause_for_candidate_selection", False)):
            result = {
                "status": "waiting_selection", "baseline": baseline_row,
                "recommended_candidate_id": selected["id"], "candidates": list_improvement_candidates(cycle_id),
                "requires_candidate_selection": True, "budget": budget, "usage": usage,
            }
            update_improvement_cycle(cycle_id, state="WAITING_SELECTION", result=result)
            append_improvement_event(
                cycle_id, "candidate_selection_required", state="WAITING_SELECTION",
                message="Candidates are ranked; choose one before entering the repair loop",
                payload={"recommended_candidate_id": selected["id"]},
            )
            return get_improvement_cycle(cycle_id) or result

        return await _validate_selected_candidates(cycle_id, selected["id"])
    except Exception as exc:
        result = {"status": "blocked", "error": str(exc)}
        update_improvement_cycle(cycle_id, state="BLOCKED_BY_CAPABILITY", result=result, stop_reason=str(exc), mark_completed=True)
        append_improvement_event(cycle_id, "cycle_stopped", state="BLOCKED_BY_CAPABILITY", message=str(exc))
        raise


async def select_improvement_candidate_for_cycle(
    cycle_id: str,
    candidate_id: str,
    *,
    experiment_mode: bool | None = None,
    experiment_candidates: int | None = None,
) -> Dict[str, Any]:
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise KeyError(cycle_id)
    if cycle.get("state") != "WAITING_SELECTION" or cycle.get("completed_at"):
        raise ValueError(f"Cycle is not waiting for candidate selection; current state={cycle.get('state')}")
    append_improvement_event(
        cycle_id, "candidate_override", state="WAITING_SELECTION", message="Candidate selected by user",
        payload={"candidate_id": candidate_id, "experiment_mode": experiment_mode, "experiment_candidates": experiment_candidates},
    )
    return await _validate_selected_candidates(
        cycle_id, candidate_id, experiment_mode=experiment_mode, experiment_candidates=experiment_candidates,
    )


def apply_improvement_cycle(cycle_id: str, *, confirm: bool) -> Dict[str, Any]:
    if not confirm:
        raise ValueError("confirm must be true to apply an improvement cycle")
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise KeyError(cycle_id)
    if cycle.get("cancel_requested"):
        cancelled = _cancel_if_requested(cycle_id)
        return cancelled or cycle
    if cycle.get("state") != "WAITING_APPROVAL":
        raise ValueError(f"Cycle is not waiting for approval; current state={cycle.get('state')}")
    policy_snapshot = cycle.get("policy_snapshot") or {}
    integrity = verify_policy_snapshot(policy_snapshot, cycle.get("policy_integrity") or {})
    if not integrity.get("passed"):
        result = {"status": "policy_integrity_blocked", "integrity": integrity}
        update_improvement_cycle(cycle_id, state="POLICY_INTEGRITY_BLOCKED", result=result, stop_reason=integrity.get("reason"), mark_completed=True)
        append_improvement_event(cycle_id, "cycle_stopped", state="POLICY_INTEGRITY_BLOCKED", message="Policy snapshot integrity failed before apply", payload=result)
        return get_improvement_cycle(cycle_id) or result
    approval_status = approval_requirement_status(cycle_id, (policy_snapshot.get("policy") or {}))
    if not approval_status.get("passed"):
        result = {"status": "approval_blocked", "approval": approval_status}
        update_improvement_cycle(cycle_id, state="APPROVAL_BLOCKED", result=result, stop_reason="approval_quorum_not_satisfied", mark_completed=True)
        append_improvement_event(cycle_id, "cycle_stopped", state="APPROVAL_BLOCKED", message="Verified approval quorum is not satisfied", payload=result)
        return get_improvement_cycle(cycle_id) or result
    issue_id = cycle.get("selected_issue_id")
    candidate_id = cycle.get("selected_candidate_id")
    if not issue_id:
        raise ValueError("Cycle has no verified repair issue_id")

    verified = get_verified_repair(issue_id)
    if verified:
        governance = evaluate_verified_candidate_governance(
            cycle["project_name"], verified.get("proposed_changes") or [], policy_snapshot=cycle.get("policy_snapshot") or None,
        )
    else:
        # Backward-compatible/manual records created before verified repair persistence
        # cannot be pre-staged here. The canonical apply path still refuses a missing
        # verified repair; tests/integrations that replace that apply path remain usable.
        governance = {
            "status": "warning", "passed": True, "project_name": cycle["project_name"],
            "violations": [],
            "warnings": [{"code": "verified_record_unavailable", "message": "Pre-apply governance staging unavailable for legacy repair record", "evidence": {"issue_id": issue_id}}],
        }
    stored_governance = store_governance_check(
        cycle_id=cycle_id, candidate_id=candidate_id, issue_id=issue_id, project_name=cycle["project_name"], result=governance,
    )
    if not governance.get("passed"):
        if candidate_id:
            update_improvement_candidate(candidate_id, status="governance_blocked", issue_id=issue_id)
        try:
            discard_verified_repair(issue_id, reason="Blocked by pre-apply Part 6 governance recheck")
        except (KeyError, ValueError):
            pass
        result = {"status": "governance_blocked", "governance": governance, "governance_check_id": stored_governance["id"]}
        update_improvement_cycle(cycle_id, state="GOVERNANCE_BLOCKED", result=result, stop_reason="governance_blocked", mark_completed=True)
        append_improvement_event(
            cycle_id, "cycle_stopped", state="GOVERNANCE_BLOCKED",
            message="Verified candidate no longer passes project governance policy", payload=result,
        )
        return get_improvement_cycle(cycle_id) or result

    _transition(cycle_id, "APPLYING", "Applying the exact verified candidate with snapshot protection", payload={"governance_check_id": stored_governance["id"]})
    applied = apply_verified_repair(issue_id, confirm=True)
    append_improvement_event(cycle_id, "apply_finished", state="APPLYING", message=f"Apply status: {applied.get('status')}", payload=applied)

    baseline_score = cycle.get("baseline_score")
    baseline_snapshot_id = cycle.get("baseline_snapshot_id")
    final_row = None
    final_score = baseline_score

    if applied.get("status") != "applied":
        if candidate_id:
            update_improvement_candidate(candidate_id, status="rolled_back", issue_id=issue_id)
        outcome = store_improvement_outcome(
            cycle_id=cycle_id, candidate_id=candidate_id, issue_id=issue_id, project_name=cycle["project_name"],
            apply_status=applied.get("status", "rolled_back"), baseline_score=baseline_score, final_score=baseline_score,
            baseline_snapshot_id=baseline_snapshot_id, final_snapshot_id=None,
            details={"apply_result": applied, "budget": cycle.get("budget", {}), "usage": cycle.get("usage", {})},
        )
        store_regression_attribution(
            cycle_id=cycle_id, project_name=cycle["project_name"], candidate_id=candidate_id, issue_id=issue_id,
            outcome_id=outcome.get("id"), baseline=None, final=None,
            changed_files=[row.get("path", "") for row in ((verified or {}).get("proposed_changes") or [])],
            apply_status=str(applied.get("status") or "rolled_back"),
        )
        result = {"status": applied.get("status"), "apply": applied, "outcome": outcome}
        update_improvement_cycle(cycle_id, state="ROLLBACK_REQUIRED", result=result, stop_reason=applied.get("rollback_reason", "apply_failed"), mark_completed=True)
        append_improvement_event(cycle_id, "cycle_stopped", state="ROLLBACK_REQUIRED", message="Apply was rolled back or failed validation")
        return get_improvement_cycle(cycle_id) or result

    _transition(cycle_id, "MONITORING", "Capturing post-apply project health")
    final = capture_project_health(cycle["project_name"], run_checks=True)
    final_row = store_health_snapshot(project_name=cycle["project_name"], snapshot=final, cycle_id=cycle_id, phase="post_apply")
    final_score = float(final.get("health_score") or 0.0)
    update_improvement_cycle(cycle_id, final_score=final_score, final_snapshot_id=final_row["id"])
    append_improvement_event(
        cycle_id, "health_captured", state="MONITORING", message=f"Post-apply health {final_score}",
        payload={"snapshot_id": final_row["id"], "health_score": final_score, "dimensions": final.get("dimensions", {})},
    )

    max_drop = float(settings.IMPROVEMENT_MAX_SCORE_REGRESSION)
    if baseline_score is not None and final_score < float(baseline_score) - max_drop:
        reason = f"Post-apply health regressed by more than {max_drop} points"
        rollback = rollback_applied_repair(issue_id, reason=reason)
        if candidate_id:
            update_improvement_candidate(candidate_id, status="rolled_back", issue_id=issue_id)
        restored = capture_project_health(cycle["project_name"], run_checks=True)
        restored_row = store_health_snapshot(project_name=cycle["project_name"], snapshot=restored, cycle_id=cycle_id, phase="post_rollback")
        outcome = store_improvement_outcome(
            cycle_id=cycle_id, candidate_id=candidate_id, issue_id=issue_id, project_name=cycle["project_name"],
            apply_status="rolled_back_health_regression", baseline_score=baseline_score,
            final_score=float(restored.get("health_score") or 0.0), baseline_snapshot_id=baseline_snapshot_id,
            final_snapshot_id=restored_row["id"],
            details={"apply_result": applied, "regressed_snapshot": final_row, "rollback": rollback, "budget": cycle.get("budget", {}), "usage": cycle.get("usage", {})},
        )
        from app.improvement_store import get_health_snapshot
        baseline_health = get_health_snapshot(baseline_snapshot_id) if baseline_snapshot_id else None
        store_regression_attribution(
            cycle_id=cycle_id, project_name=cycle["project_name"], candidate_id=candidate_id, issue_id=issue_id,
            outcome_id=outcome.get("id"), baseline=baseline_health, final=final,
            changed_files=[row.get("path", "") for row in ((verified or {}).get("proposed_changes") or [])],
            apply_status="rolled_back_health_regression",
        )
        result = {"status": "rolled_back", "reason": reason, "apply": applied, "rollback": rollback, "outcome": outcome}
        update_improvement_cycle(
            cycle_id, state="ROLLBACK_REQUIRED", final_score=float(restored.get("health_score") or 0.0),
            final_snapshot_id=restored_row["id"], result=result, stop_reason=reason, mark_completed=True,
        )
        append_improvement_event(cycle_id, "health_regression_rollback", state="ROLLBACK_REQUIRED", message=reason, payload=rollback)
        return get_improvement_cycle(cycle_id) or result

    _transition(cycle_id, "LEARNING", "Recording measured improvement outcome for future ranking")
    if candidate_id:
        update_improvement_candidate(candidate_id, status="applied", issue_id=issue_id)
    outcome = store_improvement_outcome(
        cycle_id=cycle_id, candidate_id=candidate_id, issue_id=issue_id, project_name=cycle["project_name"],
        apply_status="applied", baseline_score=baseline_score, final_score=final_score,
        baseline_snapshot_id=baseline_snapshot_id, final_snapshot_id=final_row["id"] if final_row else None,
        details={
            "apply_result": applied,
            "baseline_dimensions": (cycle.get("result") or {}).get("baseline", {}).get("dimensions"),
            "final_dimensions": final.get("dimensions", {}),
            "budget": cycle.get("budget", {}), "usage": cycle.get("usage", {}),
        },
    )
    from app.improvement_store import get_health_snapshot
    baseline_health = get_health_snapshot(baseline_snapshot_id) if baseline_snapshot_id else None
    store_regression_attribution(
        cycle_id=cycle_id, project_name=cycle["project_name"], candidate_id=candidate_id, issue_id=issue_id,
        outcome_id=outcome.get("id"), baseline=baseline_health, final=final,
        changed_files=[row.get("path", "") for row in ((verified or {}).get("proposed_changes") or [])],
        apply_status="applied",
    )
    result = {"status": "completed", "apply": applied, "final_health": final_row, "outcome": outcome}
    update_improvement_cycle(
        cycle_id, state="IDLE", final_score=final_score, final_snapshot_id=final_row["id"] if final_row else None,
        result=result, stop_reason="completed", mark_completed=True,
    )
    append_improvement_event(
        cycle_id, "cycle_completed", state="IDLE",
        message="Improvement cycle completed and measured outcome was added to strategy memory",
        payload={"outcome_id": outcome["id"], "score_delta": outcome.get("score_delta")},
    )
    return get_improvement_cycle(cycle_id) or result


def is_terminal_improvement_cycle(cycle: Dict[str, Any] | None) -> bool:
    if not cycle:
        return True
    if cycle.get("completed_at"):
        return True
    return cycle.get("state") in _PAUSED_OR_TERMINAL_STATES
