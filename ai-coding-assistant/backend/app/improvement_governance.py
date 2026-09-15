"""Deterministic governance gate for verified improvement candidates.

The gate evaluates the exact verified patch in a throw-away candidate workspace.
It protects configured paths, approved API contracts, architecture invariants and
optional dependency-manifest restrictions before a repair can reach approval.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from app.candidate_workspace import CandidateWorkspace
from app.database import get_db, init_database
from app.improvement_policy import resolved_improvement_policy
from app.patch_engine import PatchError, apply_changes
from app.project_baselines import active_project_baseline, capture_project_signature_at_root
from app.project_paths import resolve_project_root

_SOURCE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php", ".cs"}
_DEP_MANIFESTS = {
    "requirements.txt", "pyproject.toml", "poetry.lock", "Pipfile", "Pipfile.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches(path: str, rule: str) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    r = rule.replace("\\", "/").lstrip("./")
    if not r:
        return False
    if r.endswith("/"):
        return p.startswith(r)
    return p == r or p.startswith(r + "/")


def _violation(code: str, message: str, **evidence: Any) -> Dict[str, Any]:
    return {"code": code, "message": message, "evidence": evidence}


def _warning(code: str, message: str, **evidence: Any) -> Dict[str, Any]:
    return {"code": code, "message": message, "evidence": evidence}


def evaluate_verified_candidate_governance(
    project_name: str,
    proposed_changes: Iterable[Dict[str, Any]],
    *,
    policy_snapshot: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    resolved = policy_snapshot or resolved_improvement_policy(project_name)
    policy = resolved.get("policy") or {}
    root = resolve_project_root(project_name)
    changes = [dict(change) for change in proposed_changes or []]
    changed_paths = [str(change.get("path") or "").replace("\\", "/") for change in changes]
    violations: list[Dict[str, Any]] = []
    warnings: list[Dict[str, Any]] = []

    arch = policy.get("architecture") or {}
    protected_paths = arch.get("protected_paths") or []
    forbidden_paths = arch.get("forbidden_paths") or []
    for path in changed_paths:
        for rule in protected_paths:
            if _matches(path, str(rule)):
                violations.append(_violation("protected_path_change", f"Candidate changes protected path {path}", path=path, rule=rule))
        for rule in forbidden_paths:
            if _matches(path, str(rule)):
                violations.append(_violation("forbidden_path_change", f"Candidate changes forbidden path {path}", path=path, rule=rule))

    deps = policy.get("dependencies") or {}
    if not bool(deps.get("allow_manifest_changes", True)):
        touched = sorted({Path(path).name for path in changed_paths if Path(path).name in _DEP_MANIFESTS})
        if touched:
            violations.append(_violation("dependency_manifest_change_blocked", "Project policy blocks dependency manifest/lockfile changes", files=touched))

    current_signature = capture_project_signature_at_root(root, project_name=project_name)
    baseline = active_project_baseline(project_name)

    try:
        with CandidateWorkspace.create(root) as candidate:
            if changes:
                apply_changes(candidate.root, changes)
            candidate_signature = capture_project_signature_at_root(candidate.root, project_name=project_name)

            for required in arch.get("required_paths") or []:
                required_path = (candidate.root / str(required)).resolve()
                try:
                    required_path.relative_to(candidate.root)
                except ValueError:
                    violations.append(_violation("invalid_required_path", "Required-path rule escapes project root", rule=required))
                    continue
                if not required_path.exists():
                    violations.append(_violation("required_path_missing", f"Required architecture path is missing: {required}", path=required))

            max_lines = int(arch.get("max_module_lines") or 0)
            if max_lines > 0:
                for rel in changed_paths:
                    target = candidate.root / rel
                    if not target.is_file() or target.suffix.lower() not in _SOURCE_EXT:
                        continue
                    try:
                        lines = sum(1 for _ in target.open("r", encoding="utf-8"))
                    except (OSError, UnicodeDecodeError):
                        continue
                    if lines > max_lines:
                        violations.append(_violation(
                            "module_line_limit_exceeded",
                            f"Changed source module exceeds the policy line limit: {rel} ({lines}>{max_lines})",
                            path=rel, lines=lines, limit=max_lines,
                        ))

            if bool(arch.get("protect_approved_top_level_layout", False)) and baseline:
                approved_top = set((baseline.get("payload") or {}).get("top_dirs") or {})
                candidate_top = set(candidate_signature.get("top_dirs") or {})
                additions = sorted(candidate_top - approved_top)
                if additions:
                    violations.append(_violation(
                        "top_level_layout_expansion",
                        "Candidate introduces source roots outside the approved top-level architecture",
                        added_top_level=additions,
                    ))

            api_policy = policy.get("protected_api") or {}
            current_routes = set(current_signature.get("api_routes") or [])
            candidate_routes = set(candidate_signature.get("api_routes") or [])
            explicit_routes = set(str(v) for v in api_policy.get("routes") or [])
            missing_explicit = sorted(explicit_routes - candidate_routes)
            if missing_explicit:
                violations.append(_violation(
                    "protected_api_route_missing",
                    "Candidate violates explicitly protected API contract routes",
                    missing_routes=missing_explicit,
                ))

            if bool(api_policy.get("protect_approved_baseline", True)) and baseline:
                approved_routes = set((baseline.get("payload") or {}).get("api_routes") or [])
                newly_removed = sorted((approved_routes & current_routes) - candidate_routes)
                if newly_removed:
                    violations.append(_violation(
                        "approved_api_contract_removed",
                        "Candidate removes route(s) protected by the active approved API baseline",
                        removed_routes=newly_removed,
                        baseline_id=baseline.get("id"),
                    ))
                already_missing = sorted(approved_routes - current_routes)
                if already_missing:
                    warnings.append(_warning(
                        "approved_api_preexisting_drift",
                        "Approved API baseline already contains routes missing before this candidate",
                        missing_routes=already_missing,
                        baseline_id=baseline.get("id"),
                    ))

            added_routes = sorted(candidate_routes - current_routes)
            if added_routes:
                warnings.append(_warning("api_routes_added", "Candidate adds public API route(s); review before approval", routes=added_routes))
    except (PatchError, ValueError) as exc:
        violations.append(_violation("candidate_governance_staging_failed", str(exc)))
        candidate_signature = {}

    status = "blocked" if violations else ("warning" if warnings else "passed")
    return {
        "status": status,
        "passed": not violations,
        "project_name": project_name,
        "policy_id": resolved.get("policy_id"),
        "policy_version": resolved.get("version", 0),
        "changed_paths": changed_paths,
        "violations": violations,
        "warnings": warnings,
        "current_signature": {
            "api_hash": current_signature.get("api_hash"),
            "architecture_hash": current_signature.get("architecture_hash"),
        },
        "candidate_signature": {
            "api_hash": candidate_signature.get("api_hash") if candidate_signature else None,
            "architecture_hash": candidate_signature.get("architecture_hash") if candidate_signature else None,
        },
    }


def store_governance_check(
    *, cycle_id: str | None, candidate_id: str | None, issue_id: str | None,
    project_name: str, result: Dict[str, Any],
) -> Dict[str, Any]:
    init_database()
    check_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_governance_checks
               (id, cycle_id, candidate_id, issue_id, project_name, status, violations_json, warnings_json, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                check_id, cycle_id, candidate_id, issue_id, project_name, result.get("status", "unknown"),
                json.dumps(result.get("violations") or [], ensure_ascii=False),
                json.dumps(result.get("warnings") or [], ensure_ascii=False),
                json.dumps({k: v for k, v in result.items() if k not in {"violations", "warnings"}}, ensure_ascii=False, default=str), now,
            ),
        )
        conn.commit()
    return {"id": check_id, "created_at": now, **result}


def list_governance_checks(*, project_name: str | None = None, cycle_id: str | None = None, limit: int = 100) -> list[Dict[str, Any]]:
    init_database()
    query = "SELECT * FROM improvement_governance_checks"
    args: list[Any] = []
    clauses: list[str] = []
    if project_name:
        clauses.append("project_name = ?")
        args.append(project_name)
    if cycle_id:
        clauses.append("cycle_id = ?")
        args.append(cycle_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    with get_db() as conn:
        rows = conn.execute(query, tuple(args)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        for raw, clean, default in (("violations_json", "violations", []), ("warnings_json", "warnings", []), ("details_json", "details", {})):
            try:
                item[clean] = json.loads(item.pop(raw) or json.dumps(default))
            except Exception:
                item[clean] = default
        output.append(item)
    return output
