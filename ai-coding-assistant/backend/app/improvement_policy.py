"""Project-specific governance policy for manual self-improvement cycles.

Policies are deterministic, local and auditable. They can restrict risk/categories,
protect approved API contracts and architecture invariants, and tune repetition
suppression. They cannot disable the human approval requirement for live writes.
"""
from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from app.config import settings
from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_improvement_policy() -> Dict[str, Any]:
    return {
        "allowed_risks": [v.strip().lower() for v in str(settings.IMPROVEMENT_ALLOWED_RISKS).split(",") if v.strip()],
        "min_priority": float(settings.IMPROVEMENT_MIN_PRIORITY),
        "allowed_categories": [],
        "blocked_categories": [],
        "protected_api": {
            "protect_approved_baseline": True,
            "routes": [],
        },
        "architecture": {
            "required_paths": [],
            "forbidden_paths": [],
            "protected_paths": [],
            "protect_approved_top_level_layout": False,
            "max_module_lines": int(settings.IMPROVEMENT_GOVERNANCE_MAX_MODULE_LINES),
        },
        "dependencies": {
            "allow_manifest_changes": True,
        },
        "repetition": {
            "enabled": True,
            "repeat_limit": int(settings.IMPROVEMENT_REPEAT_LIMIT),
            "history_limit": int(settings.IMPROVEMENT_REPEAT_HISTORY_LIMIT),
        },
        "approval": {
            "human_source_apply_required": True,
            "min_verified_approvals": 0,
            "required_roles": [],
            "distinct_roles": False,
        },
    }


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _strings(values: Iterable[Any], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw).strip().replace("\\", "/")
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def normalize_improvement_policy(policy: Dict[str, Any] | None) -> Dict[str, Any]:
    merged = _merge(default_improvement_policy(), policy or {})
    allowed_risks = [v for v in _strings(merged.get("allowed_risks", []), limit=4) if v in {"low", "medium", "high", "critical"}]
    if not allowed_risks:
        allowed_risks = ["low", "medium"]
    merged["allowed_risks"] = allowed_risks
    merged["min_priority"] = max(0.0, float(merged.get("min_priority", settings.IMPROVEMENT_MIN_PRIORITY)))
    merged["allowed_categories"] = [v.lower() for v in _strings(merged.get("allowed_categories", []), limit=50)]
    merged["blocked_categories"] = [v.lower() for v in _strings(merged.get("blocked_categories", []), limit=50)]

    api = merged.setdefault("protected_api", {})
    api["protect_approved_baseline"] = bool(api.get("protect_approved_baseline", True))
    api["routes"] = _strings(api.get("routes", []), limit=int(settings.IMPROVEMENT_POLICY_MAX_PROTECTED_ROUTES))

    arch = merged.setdefault("architecture", {})
    max_paths = int(settings.IMPROVEMENT_POLICY_MAX_REQUIRED_PATHS)
    arch["required_paths"] = _strings(arch.get("required_paths", []), limit=max_paths)
    arch["forbidden_paths"] = _strings(arch.get("forbidden_paths", []), limit=max_paths)
    arch["protected_paths"] = _strings(arch.get("protected_paths", []), limit=max_paths)
    arch["protect_approved_top_level_layout"] = bool(arch.get("protect_approved_top_level_layout", False))
    arch["max_module_lines"] = max(50, min(int(arch.get("max_module_lines") or settings.IMPROVEMENT_GOVERNANCE_MAX_MODULE_LINES), 10000))

    deps = merged.setdefault("dependencies", {})
    deps["allow_manifest_changes"] = bool(deps.get("allow_manifest_changes", True))

    repetition = merged.setdefault("repetition", {})
    repetition["enabled"] = bool(repetition.get("enabled", True))
    repetition["repeat_limit"] = max(1, min(int(repetition.get("repeat_limit") or settings.IMPROVEMENT_REPEAT_LIMIT), 20))
    repetition["history_limit"] = max(1, min(int(repetition.get("history_limit") or settings.IMPROVEMENT_REPEAT_HISTORY_LIMIT), 500))

    # Human source-apply approval remains immutable. Part 7 optionally requires
    # authenticated role evidence before the existing explicit confirm=true apply.
    approval = merged.setdefault("approval", {})
    approval["human_source_apply_required"] = True
    approval["min_verified_approvals"] = max(0, min(int(approval.get("min_verified_approvals") or 0), 10))
    approval["required_roles"] = [v.lower() for v in _strings(approval.get("required_roles", []), limit=10)]
    approval["distinct_roles"] = bool(approval.get("distinct_roles", False))
    return merged


def save_improvement_policy(project_name: str, policy: Dict[str, Any], *, activate: bool = True) -> Dict[str, Any]:
    init_database()
    normalized = normalize_improvement_policy(policy)
    now = _now()
    policy_id = str(uuid.uuid4())
    with get_db() as conn:
        row = conn.execute("SELECT MAX(version) FROM improvement_policies WHERE project_name = ?", (project_name,)).fetchone()
        version = int((row[0] if row else 0) or 0) + 1
        if activate:
            conn.execute("UPDATE improvement_policies SET active = 0 WHERE project_name = ?", (project_name,))
        conn.execute(
            """INSERT INTO improvement_policies
               (id, project_name, version, policy_json, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (policy_id, project_name, version, json.dumps(normalized, ensure_ascii=False), 1 if activate else 0, now, now),
        )
        conn.commit()
    return get_improvement_policy(policy_id) or {"id": policy_id, "project_name": project_name, "version": version, "policy": normalized}


def _row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["policy"] = json.loads(item.pop("policy_json"))
    except Exception:
        item["policy"] = default_improvement_policy()
    item["active"] = bool(item.get("active"))
    return item


def get_improvement_policy(policy_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_policies WHERE id = ?", (policy_id,)).fetchone()
    return _row(row) if row else None


def active_improvement_policy(project_name: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM improvement_policies WHERE project_name = ? AND active = 1 ORDER BY version DESC LIMIT 1",
            (project_name,),
        ).fetchone()
    return _row(row) if row else None


def list_improvement_policies(project_name: str, *, limit: int = 50) -> list[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM improvement_policies WHERE project_name = ? ORDER BY version DESC LIMIT ?",
            (project_name, max(1, min(int(limit), 200))),
        ).fetchall()
    return [_row(row) for row in rows]


def resolved_improvement_policy(project_name: str) -> Dict[str, Any]:
    active = active_improvement_policy(project_name)
    policy = normalize_improvement_policy((active or {}).get("policy") or {})
    return {
        "project_name": project_name,
        "policy_id": (active or {}).get("id"),
        "version": (active or {}).get("version", 0),
        "source": "project" if active else "defaults",
        "policy": policy,
    }


def candidate_allowed_by_policy(candidate: Dict[str, Any], policy: Dict[str, Any]) -> tuple[bool, str | None]:
    risk = str(candidate.get("risk") or "medium").lower()
    if risk not in set(policy.get("allowed_risks") or []):
        return False, f"risk_not_allowed:{risk}"
    if float(candidate.get("priority_score") or 0.0) < float(policy.get("min_priority") or 0.0):
        return False, "below_policy_min_priority"
    finding = (candidate.get("evidence") or {}).get("health_finding") or {}
    category = str(finding.get("category") or "generic").lower()
    allowed_categories = set(policy.get("allowed_categories") or [])
    blocked_categories = set(policy.get("blocked_categories") or [])
    if allowed_categories and category not in allowed_categories:
        return False, f"category_not_allowed:{category}"
    if category in blocked_categories:
        return False, f"category_blocked:{category}"
    if bool(candidate.get("suppressed")):
        return False, str(candidate.get("suppression_reason") or "repeated_candidate_suppressed")
    if candidate.get("cooldown_until"):
        return False, str(candidate.get("cooldown_reason") or "candidate_failure_cooldown")
    return True, None
