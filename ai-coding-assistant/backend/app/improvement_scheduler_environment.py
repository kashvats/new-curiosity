"""Environment policies and CI identity binding for Part 9 scheduler hardening."""
from __future__ import annotations

import subprocess
from typing import Any, Dict

from app.config import settings
from app.improvement_scheduler_security import operator_auth_configured, signed_webhook_configured
from app.project_paths import resolve_project_root

_ENVIRONMENTS = {"dev", "staging", "prod"}


def normalize_environment(value: str | None) -> str:
    env = str(value or "dev").strip().lower()
    return env if env in _ENVIRONMENTS else "dev"


def environment_policy(environment: str | None) -> Dict[str, Any]:
    env = normalize_environment(environment)
    if env == "prod":
        return {
            "environment": env,
            "min_interval_minutes": max(int(settings.IMPROVEMENT_SCHEDULER_MIN_INTERVAL_MINUTES), int(settings.IMPROVEMENT_SCHEDULER_PROD_MIN_INTERVAL_MINUTES)),
            "require_readiness": True,
            "require_ci_success": True,
            "require_slo": True,
            "require_signed_webhook": True,
            "require_ci_binding": True,
            "require_operator_registry": True,
        }
    if env == "staging":
        return {
            "environment": env,
            "min_interval_minutes": max(int(settings.IMPROVEMENT_SCHEDULER_MIN_INTERVAL_MINUTES), int(settings.IMPROVEMENT_SCHEDULER_STAGING_MIN_INTERVAL_MINUTES)),
            "require_readiness": True,
            "require_ci_success": True,
            "require_slo": False,
            "require_signed_webhook": True,
            "require_ci_binding": True,
            "require_operator_registry": False,
        }
    return {
        "environment": "dev",
        "min_interval_minutes": int(settings.IMPROVEMENT_SCHEDULER_MIN_INTERVAL_MINUTES),
        "require_readiness": False,
        "require_ci_success": False,
        "require_slo": False,
        "require_signed_webhook": False,
        "require_ci_binding": False,
        "require_operator_registry": False,
    }


def project_git_identity(project_name: str) -> Dict[str, Any]:
    root = resolve_project_root(project_name)
    result: Dict[str, Any] = {"available": False, "commit_sha": None, "branch": None}
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False,
        )
        branch = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=5, check=False,
        )
        if commit.returncode == 0:
            result["commit_sha"] = commit.stdout.strip()
            result["branch"] = branch.stdout.strip() if branch.returncode == 0 else None
            result["available"] = True
    except Exception:
        pass
    return result


def expected_ci_identity(schedule: Dict[str, Any]) -> Dict[str, Any]:
    expected_branch = str(schedule.get("ci_branch") or "").strip() or None
    expected_commit = str(schedule.get("ci_commit_sha") or "").strip() or None
    project_identity = None
    if bool(schedule.get("bind_ci_to_project_head")):
        project_identity = project_git_identity(schedule["project_name"])
        if project_identity.get("available"):
            expected_commit = project_identity.get("commit_sha")
            if not expected_branch:
                expected_branch = project_identity.get("branch")
    return {
        "expected_branch": expected_branch,
        "expected_commit_sha": expected_commit,
        "bind_ci_to_project_head": bool(schedule.get("bind_ci_to_project_head")),
        "project_git": project_identity,
    }


def environment_policy_status(schedule: Dict[str, Any]) -> Dict[str, Any]:
    policy = environment_policy(schedule.get("environment"))
    failures: list[str] = []
    if int(schedule.get("interval_minutes") or 0) < int(policy["min_interval_minutes"]):
        failures.append("interval_below_environment_minimum")
    for field in ("require_readiness", "require_ci_success", "require_slo"):
        if policy[field] and not bool(schedule.get(field)):
            failures.append(field)
    if policy["require_signed_webhook"] and not signed_webhook_configured():
        failures.append("signed_webhook_not_configured")
    binding = expected_ci_identity(schedule)
    if policy["require_ci_binding"] and not (binding.get("expected_branch") or binding.get("expected_commit_sha")):
        failures.append("ci_identity_binding_missing")
    if policy["require_operator_registry"] and not operator_auth_configured():
        failures.append("operator_registry_not_configured")
    return {
        "name": "environment_policy",
        "passed": not failures,
        "message": "Environment policy requirements pass" if not failures else "Environment policy blocks this scheduled run",
        "evidence": {"policy": policy, "failures": failures, "ci_binding": binding},
    }
