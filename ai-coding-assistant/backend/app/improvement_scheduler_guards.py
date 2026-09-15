"""Deterministic Part 8 scheduler gates.

No gate can authorize source apply. These checks only decide whether a dry-run
observe/propose schedule is allowed to execute at a point in time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.autonomy_readiness import autonomy_readiness_report
from app.config import settings
from app.improvement_scheduler_environment import environment_policy_status, expected_ci_identity
from app.improvement_scheduler_security import legacy_webhook_token_configured, signed_webhook_configured
from app.improvement_scheduler_store import (
    count_scheduler_runs,
    get_scheduler_control,
    list_ci_evidence,
    list_slo_evidence,
)

_DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _utc_now(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _gate(name: str, passed: bool, message: str, evidence: Any = None) -> Dict[str, Any]:
    return {"name": name, "passed": bool(passed), "message": message, "evidence": evidence}


def maintenance_window_status(schedule: Dict[str, Any], *, now: datetime | None = None) -> Dict[str, Any]:
    windows = schedule.get("maintenance_windows") or []
    if not windows:
        return _gate("maintenance_window", True, "No maintenance window restriction configured", {"restricted": False})
    timezone_name = str(schedule.get("timezone") or "UTC")
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return _gate("maintenance_window", False, f"Invalid schedule timezone: {timezone_name}", {"timezone": timezone_name})
    local = _utc_now(now).astimezone(tz)
    minute = local.hour * 60 + local.minute
    weekday = local.weekday()
    for raw in windows:
        days = raw.get("days") or []
        allowed_days = {_DAY_NAMES.get(str(day).strip().lower()[:3], -1) for day in days}
        if days and weekday not in allowed_days:
            continue
        try:
            sh, sm = [int(v) for v in str(raw.get("start") or "00:00").split(":", 1)]
            eh, em = [int(v) for v in str(raw.get("end") or "23:59").split(":", 1)]
            start = sh * 60 + sm
            end = eh * 60 + em
        except Exception:
            continue
        inside = (start <= minute <= end) if start <= end else (minute >= start or minute <= end)
        if inside:
            return _gate("maintenance_window", True, "Current time is inside an allowed maintenance window", {"timezone": timezone_name, "local_time": local.isoformat(), "window": raw})
    return _gate("maintenance_window", False, "Current time is outside all configured maintenance windows", {"timezone": timezone_name, "local_time": local.isoformat(), "windows": windows})


def kill_switch_status(project_name: str) -> Dict[str, Any]:
    global_control = get_scheduler_control("global")
    project_control = get_scheduler_control(f"project:{project_name}")
    active = bool(global_control.get("kill_switch") or project_control.get("kill_switch"))
    reason = project_control.get("reason") if project_control.get("kill_switch") else global_control.get("reason")
    return _gate("emergency_kill_switch", not active, "Kill switch is clear" if not active else "Scheduler blocked by emergency kill switch", {"active": active, "reason": reason, "global": global_control, "project": project_control})


def rate_limit_status(schedule: Dict[str, Any], *, now: datetime | None = None) -> Dict[str, Any]:
    now = _utc_now(now)
    hour_cutoff = (now - timedelta(hours=1)).isoformat()
    day_cutoff = (now - timedelta(hours=24)).isoformat()
    global_runs = count_scheduler_runs(since_iso=hour_cutoff)
    project_runs = count_scheduler_runs(since_iso=day_cutoff, project_name=schedule["project_name"])
    schedule_runs = count_scheduler_runs(since_iso=day_cutoff, schedule_id=schedule["id"])
    global_limit = max(1, int(settings.IMPROVEMENT_SCHEDULER_MAX_GLOBAL_RUNS_PER_HOUR))
    project_limit = max(1, int(settings.IMPROVEMENT_SCHEDULER_MAX_PROJECT_RUNS_PER_DAY))
    schedule_limit = int(schedule.get("max_runs_per_day") or project_limit)
    passed = global_runs <= global_limit and project_runs <= project_limit and schedule_runs <= schedule_limit
    return _gate(
        "rate_limits", passed,
        "Scheduler rate limits allow this run" if passed else "Scheduler rate limit reached",
        {"global_last_hour": global_runs, "global_limit": global_limit, "project_last_24h": project_runs, "project_limit": project_limit, "schedule_last_24h": schedule_runs, "schedule_limit": schedule_limit},
    )


def evidence_authentication_status(schedule: Dict[str, Any]) -> Dict[str, Any]:
    requires_external_evidence = bool(schedule.get("require_ci_success") or schedule.get("require_slo"))
    signed = signed_webhook_configured()
    legacy = legacy_webhook_token_configured()
    configured = signed or legacy
    passed = (not requires_external_evidence) or configured
    return _gate(
        "evidence_webhook_auth", passed,
        "Webhook evidence authentication is configured" if passed and requires_external_evidence else (
            "External evidence is not required" if passed else "CI/SLO-gated schedules require signed webhook or legacy token authentication"
        ),
        {"required": requires_external_evidence, "configured": configured, "signed_hmac": signed, "legacy_token": legacy},
    )


def ci_evidence_status(schedule: Dict[str, Any], *, now: datetime | None = None) -> Dict[str, Any]:
    if not schedule.get("require_ci_success"):
        return _gate("ci_evidence", True, "CI success evidence is not required by this schedule", {"required": False})
    rows = list_ci_evidence(schedule["project_name"], limit=50)
    binding = expected_ci_identity(schedule)
    expected_branch = binding.get("expected_branch")
    expected_commit = binding.get("expected_commit_sha")
    if binding.get("bind_ci_to_project_head") and not (binding.get("project_git") or {}).get("available"):
        return _gate("ci_evidence", False, "CI binding requires a readable project Git HEAD", {"binding": binding})

    def matches(item: Dict[str, Any]) -> bool:
        if expected_branch and str(item.get("branch") or "") != str(expected_branch):
            return False
        if expected_commit and str(item.get("commit_sha") or "") != str(expected_commit):
            return False
        return True

    latest = next((item for item in rows if matches(item)), None)
    if not latest:
        return _gate("ci_evidence", False, "No CI evidence matches the configured branch/commit binding", {"required": True, "binding": binding, "available_samples": len(rows)})
    received = _parse_iso(latest.get("received_at"))
    age_minutes = None if not received else (_utc_now(now) - received).total_seconds() / 60.0
    fresh = age_minutes is not None and age_minutes <= float(settings.IMPROVEMENT_SCHEDULER_CI_MAX_AGE_MINUTES)
    successful = str(latest.get("status") or "").strip().lower() in {"success", "successful", "passed", "pass", "succeeded", "green"}
    passed = fresh and successful
    return _gate(
        "ci_evidence", passed,
        "Bound CI evidence is successful and fresh" if passed else "Bound CI evidence is stale or failing",
        {"latest": latest, "binding": binding, "age_minutes": None if age_minutes is None else round(age_minutes, 2), "max_age_minutes": settings.IMPROVEMENT_SCHEDULER_CI_MAX_AGE_MINUTES},
    )


def slo_evidence_status(schedule: Dict[str, Any], *, now: datetime | None = None) -> Dict[str, Any]:
    if not schedule.get("require_slo"):
        return _gate("slo_error_budget", True, "SLO/error-budget evidence is not required by this schedule", {"required": False})
    rows = list_slo_evidence(schedule["project_name"], limit=1)
    latest = rows[0] if rows else None
    if not latest:
        return _gate("slo_error_budget", False, "No SLO/error-budget evidence has been ingested", {"required": True})
    created = _parse_iso(latest.get("created_at"))
    age_minutes = None if not created else (_utc_now(now) - created).total_seconds() / 60.0
    checks = {
        "fresh": age_minutes is not None and age_minutes <= float(settings.IMPROVEMENT_SCHEDULER_SLO_MAX_AGE_MINUTES),
        "error_budget": latest.get("error_budget_remaining") is not None and float(latest["error_budget_remaining"]) >= float(settings.IMPROVEMENT_SCHEDULER_SLO_MIN_ERROR_BUDGET),
        "availability": latest.get("availability") is not None and float(latest["availability"]) >= float(settings.IMPROVEMENT_SCHEDULER_SLO_MIN_AVAILABILITY),
        "error_rate": latest.get("error_rate") is not None and float(latest["error_rate"]) <= float(settings.IMPROVEMENT_SCHEDULER_SLO_MAX_ERROR_RATE),
        "latency_p95": latest.get("latency_p95_ms") is not None and float(latest["latency_p95_ms"]) <= float(settings.IMPROVEMENT_SCHEDULER_SLO_MAX_P95_MS),
    }
    passed = all(checks.values())
    return _gate("slo_error_budget", passed, "SLO and error-budget gates pass" if passed else "SLO/error-budget gate blocks this scheduled run", {"latest": latest, "checks": checks, "age_minutes": None if age_minutes is None else round(age_minutes, 2), "thresholds": {"max_age_minutes": settings.IMPROVEMENT_SCHEDULER_SLO_MAX_AGE_MINUTES, "min_error_budget": settings.IMPROVEMENT_SCHEDULER_SLO_MIN_ERROR_BUDGET, "min_availability": settings.IMPROVEMENT_SCHEDULER_SLO_MIN_AVAILABILITY, "max_error_rate": settings.IMPROVEMENT_SCHEDULER_SLO_MAX_ERROR_RATE, "max_p95_ms": settings.IMPROVEMENT_SCHEDULER_SLO_MAX_P95_MS}})


def readiness_status(schedule: Dict[str, Any]) -> Dict[str, Any]:
    if not schedule.get("require_readiness"):
        return _gate("autonomy_readiness", True, "Readiness gate disabled for this dry-run schedule", {"required": False})
    report = autonomy_readiness_report(schedule["project_name"])
    return _gate("autonomy_readiness", bool(report.get("eligible")), "Project passes Part 7 readiness gates" if report.get("eligible") else "Project is not yet eligible for guarded scheduling", {"verdict": report.get("verdict"), "blockers": report.get("blockers", []), "summary": report.get("summary")})


def evaluate_schedule_guards(schedule: Dict[str, Any], *, now: datetime | None = None, include_readiness: bool = True) -> Dict[str, Any]:
    gates = [
        kill_switch_status(schedule["project_name"]),
        environment_policy_status(schedule),
        maintenance_window_status(schedule, now=now),
        rate_limit_status(schedule, now=now),
        evidence_authentication_status(schedule),
        ci_evidence_status(schedule, now=now),
        slo_evidence_status(schedule, now=now),
    ]
    if include_readiness:
        gates.append(readiness_status(schedule))
    blockers = [gate for gate in gates if not gate["passed"]]
    return {"passed": not blockers, "gates": gates, "blockers": blockers}
