"""Historical test/check impact memory for verified improvement experiments."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from app.config import settings
from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else default
    except Exception:
        return default


def _normalized_checks(validation: Dict[str, Any]) -> list[Dict[str, Any]]:
    checks: list[Dict[str, Any]] = []
    for row in validation.get("checks") or []:
        args = [str(v) for v in (row.get("args") or []) if str(v)]
        if not args:
            continue
        checks.append({
            "args": args,
            "purpose": str(row.get("purpose") or "Historical validation check"),
            "passed": bool(row.get("passed")),
        })
    return checks[:50]




def _coverage_signals(validation: Dict[str, Any]) -> Dict[str, Any]:
    signals: Dict[str, Any] = {}
    for key in ("coverage", "coverage_percent", "line_coverage", "branch_coverage"):
        value = validation.get(key)
        if value is not None and isinstance(value, (int, float, str, dict)):
            signals[key] = value
    metrics = validation.get("metrics")
    if isinstance(metrics, dict):
        for key, value in metrics.items():
            if "coverage" in str(key).lower() and isinstance(value, (int, float, str)):
                signals[str(key)] = value
    for check in validation.get("checks") or []:
        if isinstance(check, dict) and check.get("coverage") is not None:
            signals[f"check:{check.get('purpose') or 'validation'}"] = check.get("coverage")
    return signals

def store_test_impact(
    *, cycle_id: str, candidate_id: str | None, issue_id: str | None, project_name: str,
    changed_files: Iterable[str], validation: Dict[str, Any], quality_score: float | None,
) -> Dict[str, Any]:
    init_database()
    impact_id = str(uuid.uuid4())
    files = sorted({str(v).replace("\\", "/") for v in changed_files if str(v).strip()})[:100]
    checks = _normalized_checks(validation)
    coverage = _coverage_signals(validation)
    passed = bool(validation.get("passed")) and all(row.get("passed") for row in checks) if checks else bool(validation.get("passed"))
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_test_impacts
               (id, cycle_id, candidate_id, issue_id, project_name, changed_files_json, checks_json, coverage_json, passed, quality_score, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (impact_id, cycle_id, candidate_id, issue_id, project_name, json.dumps(files), json.dumps(checks), json.dumps(coverage, ensure_ascii=False, default=str), 1 if passed else 0, quality_score, _now()),
        )
        conn.commit()
    return {"id": impact_id, "changed_files": files, "checks": checks, "coverage": coverage, "passed": passed, "quality_score": quality_score}


def test_impact_memory(project_name: str, files: Iterable[str], *, limit: int | None = None) -> Dict[str, Any]:
    init_database()
    targets = {str(v).replace("\\", "/") for v in files if str(v).strip()}
    limit = max(1, min(int(limit or settings.IMPROVEMENT_TEST_IMPACT_HISTORY_LIMIT), 1000))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM improvement_test_impacts WHERE project_name = ? ORDER BY created_at DESC LIMIT ?",
            (project_name, limit),
        ).fetchall()
    matching = []
    check_stats: dict[tuple[str, ...], Dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        changed = set(_loads(item.get("changed_files_json"), []))
        overlap = sorted(targets & changed) if targets else sorted(changed)
        if targets and not overlap:
            continue
        checks = _loads(item.get("checks_json"), [])
        coverage = _loads(item.get("coverage_json"), {})
        matching.append({"id": item["id"], "overlap": overlap, "passed": bool(item.get("passed")), "quality_score": item.get("quality_score"), "coverage": coverage})
        for check in checks:
            args = tuple(str(v) for v in (check.get("args") or []))
            if not args:
                continue
            stat = check_stats.setdefault(args, {"args": list(args), "purpose": check.get("purpose") or "Historical validation check", "samples": 0, "passes": 0})
            stat["samples"] += 1
            stat["passes"] += 1 if check.get("passed") else 0
    suggested = []
    for stat in check_stats.values():
        stat["pass_rate"] = round(stat["passes"] / max(1, stat["samples"]), 4)
        suggested.append(stat)
    suggested.sort(key=lambda row: (-int(row["samples"]), -float(row["pass_rate"]), tuple(row["args"])))
    return {
        "files": sorted(targets),
        "samples": len(matching),
        "matching_runs": matching[:20],
        "coverage_signals": [row.get("coverage") for row in matching[:20] if row.get("coverage")],
        "suggested_checks": suggested[:10],
    }


def enrich_candidates_with_test_impact(project_name: str, candidates: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    output = []
    for raw in candidates:
        item = dict(raw)
        memory = test_impact_memory(project_name, item.get("likely_files") or [])
        plan = list(item.get("validation_plan") or [])
        seen = {tuple(check.get("args") or []) for check in plan}
        for check in memory.get("suggested_checks") or []:
            args = tuple(check.get("args") or [])
            if args and args not in seen:
                seen.add(args)
                plan.append({"args": list(args), "purpose": f"Impact-memory: {check.get('purpose') or 'historical check'}"})
        item["impact_memory"] = memory
        item["validation_plan"] = plan[:25]
        output.append(item)
    return output
