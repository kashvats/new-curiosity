"""Deterministic guarded-autonomy eligibility report.

A `safe_to_automate` verdict means the project satisfies the configured evidence
gates for *considering* future guarded scheduling. This module never enables a
scheduler and never relaxes explicit source-apply approval.
"""
from __future__ import annotations

from typing import Any, Dict

from app.config import settings
from app.dependency_health import analyze_dependency_health
from app.improvement_approvals import approver_registry
from app.improvement_coverage import list_coverage_reports
from app.improvement_governance import list_governance_checks
from app.improvement_policy import resolved_improvement_policy
from app.improvement_regression_attribution import list_regression_attributions
from app.improvement_store import latest_health_snapshot, list_improvement_outcomes
from app.project_baselines import active_project_baseline, project_drift
from app.project_paths import resolve_project_root


def _gate(name: str, passed: bool, *, required: bool = True, evidence: Any = None, message: str = "") -> Dict[str, Any]:
    return {"name": name, "passed": bool(passed), "required": bool(required), "message": message, "evidence": evidence}


def autonomy_readiness_report(project_name: str) -> Dict[str, Any]:
    root = resolve_project_root(project_name)
    policy_record = resolved_improvement_policy(project_name)
    policy = policy_record.get("policy") or {}
    health = latest_health_snapshot(project_name)
    baseline = active_project_baseline(project_name)
    drift = project_drift(project_name)
    deps = analyze_dependency_health(root)
    coverage_rows = list_coverage_reports(project_name, limit=1)
    coverage = coverage_rows[0] if coverage_rows else None
    outcomes = list_improvement_outcomes(project_name=project_name, limit=int(settings.IMPROVEMENT_READINESS_LOOKBACK))
    regressions = list_regression_attributions(project_name, limit=int(settings.IMPROVEMENT_READINESS_LOOKBACK))
    governance = list_governance_checks(project_name=project_name, limit=int(settings.IMPROVEMENT_READINESS_LOOKBACK))
    approvals = policy.get("approval") or {}
    credentials = approver_registry()

    applied = [row for row in outcomes if row.get("apply_status") == "applied"]
    rollbacks = [row for row in outcomes if str(row.get("apply_status") or "").startswith("rolled_back")]
    total_measured = len(applied) + len(rollbacks)
    rollback_rate = (len(rollbacks) / total_measured) if total_measured else 1.0
    regression_records = [row for row in regressions if row.get("failure_class") in {"health_regression", "dimension_regression", "rollback"}]
    governance_blocks = [row for row in governance if row.get("status") == "blocked"]
    high_findings = []
    if health:
        high_findings = [row for row in (health.get("findings") or []) if str(row.get("severity") or "").lower() in {"critical", "high"}]

    required_roles = {str(v).lower() for v in approvals.get("required_roles") or []}
    registry_roles = {str(v.get("role") or "").lower() for v in credentials.values()}
    min_approvals = int(approvals.get("min_verified_approvals") or 0)
    signed_configured = bool(str(getattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "") or ""))
    line_coverage = coverage.get("line_coverage") if coverage else None

    gates = [
        _gate("active_project_policy", policy_record.get("source") == "project", evidence={"version": policy_record.get("version")}, message="Use an explicit versioned project policy, not defaults."),
        _gate("signed_policy_snapshots", signed_configured, evidence={"algorithm": "hmac-sha256" if signed_configured else "sha256-only"}, message="Configure IMPROVEMENT_POLICY_SIGNING_KEY."),
        _gate("authenticated_approval_roles", bool(credentials) and min_approvals >= 1 and required_roles.issubset(registry_roles), evidence={"configured_approvers": len(credentials), "minimum": min_approvals, "required_roles": sorted(required_roles), "registry_roles": sorted(registry_roles)}, message="Configure authenticated approvers and require at least one verified approval."),
        _gate("approved_project_baseline", baseline is not None, evidence={"baseline_id": (baseline or {}).get("id")}, message="Capture and activate an approved API/architecture baseline."),
        _gate("health_threshold", health is not None and float(health.get("health_score") or 0) >= float(settings.IMPROVEMENT_READINESS_MIN_HEALTH) and not high_findings, evidence={"score": (health or {}).get("health_score"), "high_findings": len(high_findings)}, message=f"Persist health >= {settings.IMPROVEMENT_READINESS_MIN_HEALTH} with no high/critical findings."),
        _gate("approved_contract_no_drift", baseline is not None and not bool(drift.get("changed")), evidence={"status": drift.get("status"), "changed": drift.get("changed")}, message="Resolve drift from the approved baseline."),
        _gate("coverage_evidence", coverage is not None and line_coverage is not None and float(line_coverage) >= float(settings.IMPROVEMENT_READINESS_MIN_COVERAGE), evidence={"line_coverage": line_coverage, "minimum": settings.IMPROVEMENT_READINESS_MIN_COVERAGE}, message="Ingest a real coverage report meeting the configured line-coverage threshold."),
        _gate("dependency_health", float(deps.get("score") or 0) >= float(settings.IMPROVEMENT_READINESS_MIN_DEPENDENCY_SCORE), evidence={"score": deps.get("score")}, message="Improve dependency reproducibility/health."),
        _gate("successful_cycle_evidence", len(applied) >= int(settings.IMPROVEMENT_READINESS_MIN_SUCCESSFUL_CYCLES), evidence={"successful_cycles": len(applied), "minimum": settings.IMPROVEMENT_READINESS_MIN_SUCCESSFUL_CYCLES}, message="Accumulate successful measured manual improvement cycles."),
        _gate("rollback_rate", total_measured > 0 and rollback_rate <= float(settings.IMPROVEMENT_READINESS_MAX_ROLLBACK_RATE), evidence={"rollback_rate": round(rollback_rate, 4), "rollbacks": len(rollbacks), "measured": total_measured}, message="Rollback rate is too high or there is insufficient measured history."),
        _gate("recent_regression_attribution", len(regression_records) == 0, evidence={"recent_regressions": len(regression_records)}, message="Recent measured regression/rollback attribution must be clear."),
        _gate("recent_governance_blocks", len(governance_blocks) == 0, evidence={"blocked_checks": len(governance_blocks)}, message="Resolve recent governance-blocked candidate behavior."),
    ]
    blockers = [gate for gate in gates if gate["required"] and not gate["passed"]]
    safe = not blockers
    return {
        "project_name": project_name,
        "verdict": "safe_to_automate" if safe else "not_safe_to_automate",
        "eligible": safe,
        "scheduler_enabled": bool(settings.IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED),
        "scheduler_mode": "observe_propose_only" if settings.IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED else "disabled",
        "automatic_source_apply_enabled": False,
        "gates": gates,
        "blockers": blockers,
        "summary": {"passed": sum(1 for gate in gates if gate["passed"]), "total": len(gates), "required_blockers": len(blockers)},
        "note": "Eligibility may permit the Part 8 dry-run scheduler when separately enabled; scheduled execution remains observe/propose-only and cannot bypass human source-apply approval.",
    }
