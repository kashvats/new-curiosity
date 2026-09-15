"""Lightweight evaluation/efficiency reporting for v1.1.

This does not claim benchmark quality without external tasks.  It gives a reproducible
view over recorded repair runs and can score explicit benchmark results supplied by a
CI/evaluation harness.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from typing import Any, Dict, Iterable, List

from app.database import get_db, init_database


def _nonnegative_int(value: Any, field: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Benchmark field '{field}' must be an integer") from exc
    return max(0, parsed)


def repair_efficiency_summary(project_name: str | None = None, *, limit: int = 500) -> Dict[str, Any]:
    init_database()
    limit = max(1, min(int(limit), 5000))
    with get_db() as conn:
        if project_name:
            rows = conn.execute(
                """SELECT r.issue_id,r.attempt_no,r.validation_result_json,r.quality_score
                   FROM repair_attempts r
                   WHERE r.issue_id IN (SELECT issue_id FROM engineering_experiences WHERE project_name=?)
                   ORDER BY r.created_at DESC LIMIT ?""",
                (project_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT issue_id,attempt_no,validation_result_json,quality_score FROM repair_attempts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    issues: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        try:
            validation = json.loads(item.get("validation_result_json") or "{}")
        except Exception:
            validation = {}
        item["validation"] = validation
        issues.setdefault(str(item["issue_id"]), []).append(item)
    verified = 0
    total_attempts = 0
    repeated_failures = 0
    for attempts in issues.values():
        total_attempts += len(attempts)
        if any(a["validation"].get("passed") and (a["validation"].get("quality", {}).get("accepted", True)) for a in attempts):
            verified += 1
        signatures = [str(a["validation"].get("status") or "") for a in attempts if not a["validation"].get("passed")]
        if len(signatures) != len(set(signatures)) and signatures:
            repeated_failures += 1
    count = len(issues)
    return {
        "project_name": project_name,
        "issues_sampled": count,
        "attempts_sampled": total_attempts,
        "verified_issue_rate": round(verified / count, 4) if count else None,
        "average_attempts_per_issue": round(total_attempts / count, 3) if count else None,
        "issues_with_repeated_failure_status": repeated_failures,
        "note": "Historical operational metrics; use benchmark runs below for version-to-version quality claims.",
    }


def record_benchmark_run(*, version: str, suite_name: str, cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    init_database()
    cases = list(cases)
    if not cases:
        raise ValueError("Benchmark run requires at least one case")
    normalized: list[dict[str, Any]] = []
    for case in cases:
        normalized.append({
            "case_id": str(case.get("case_id") or case.get("id") or len(normalized) + 1),
            "passed": bool(case.get("passed")),
            "regression": bool(case.get("regression", False)),
            "llm_calls": _nonnegative_int(case.get("llm_calls", 0), "llm_calls"),
            "tokens": _nonnegative_int(case.get("tokens", 0), "tokens"),
            "duration_ms": _nonnegative_int(case.get("duration_ms", 0), "duration_ms"),
            "files_changed": _nonnegative_int(case.get("files_changed", 0), "files_changed"),
        })
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    passed = sum(1 for c in normalized if c["passed"])
    summary = {
        "cases": len(normalized),
        "passed": passed,
        "success_rate": round(passed / len(normalized), 4),
        "regression_rate": round(sum(1 for c in normalized if c["regression"]) / len(normalized), 4),
        "avg_llm_calls": round(sum(c["llm_calls"] for c in normalized) / len(normalized), 3),
        "avg_tokens": round(sum(c["tokens"] for c in normalized) / len(normalized), 1),
        "avg_duration_ms": round(sum(c["duration_ms"] for c in normalized) / len(normalized), 1),
        "avg_files_changed": round(sum(c["files_changed"] for c in normalized) / len(normalized), 3),
    }
    with get_db() as conn:
        conn.execute(
            """INSERT INTO v11_benchmark_runs(id,version,suite_name,cases_json,summary_json,created_at)
               VALUES(?,?,?,?,?,?)""",
            (run_id, version, suite_name, json.dumps(normalized), json.dumps(summary), now),
        )
        conn.commit()
    return {"id": run_id, "version": version, "suite_name": suite_name, "summary": summary, "created_at": now}


def list_benchmark_runs(*, suite_name: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if suite_name:
            rows = conn.execute("SELECT * FROM v11_benchmark_runs WHERE suite_name=? ORDER BY created_at DESC LIMIT ?", (suite_name, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM v11_benchmark_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["cases"] = json.loads(item.pop("cases_json") or "[]")
        item["summary"] = json.loads(item.pop("summary_json") or "{}")
        out.append(item)
    return out


def compare_benchmark_versions(*, suite_name: str, baseline_version: str, candidate_version: str) -> Dict[str, Any]:
    runs = list_benchmark_runs(suite_name=suite_name, limit=500)
    baseline = next((r for r in runs if r.get("version") == baseline_version), None)
    candidate = next((r for r in runs if r.get("version") == candidate_version), None)
    if not baseline or not candidate:
        missing = []
        if not baseline:
            missing.append(baseline_version)
        if not candidate:
            missing.append(candidate_version)
        raise ValueError(f"Missing benchmark run for version(s): {', '.join(missing)}")
    b = baseline.get("summary") or {}
    c = candidate.get("summary") or {}
    metrics = ["success_rate", "regression_rate", "avg_llm_calls", "avg_tokens", "avg_duration_ms", "avg_files_changed"]
    deltas = {}
    for metric in metrics:
        bv = float(b.get(metric, 0) or 0)
        cv = float(c.get(metric, 0) or 0)
        deltas[metric] = round(cv - bv, 4)
    improved = {
        "success_rate": deltas["success_rate"] > 0,
        "regression_rate": deltas["regression_rate"] < 0,
        "avg_llm_calls": deltas["avg_llm_calls"] < 0,
        "avg_tokens": deltas["avg_tokens"] < 0,
        "avg_duration_ms": deltas["avg_duration_ms"] < 0,
        "avg_files_changed": deltas["avg_files_changed"] < 0,
    }
    return {
        "suite_name": suite_name,
        "baseline": {"version": baseline_version, "run_id": baseline.get("id"), "summary": b},
        "candidate": {"version": candidate_version, "run_id": candidate.get("id"), "summary": c},
        "deltas_candidate_minus_baseline": deltas,
        "improved": improved,
        "improved_metric_count": sum(1 for value in improved.values() if value),
        "note": "Success-rate increases are better; regression/calls/tokens/duration/files deltas are better when negative.",
    }
