"""Baseline-vs-current regression comparison for JSON debug/health reports."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.database import get_db, init_database


def _load_report(value: str | Path | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    path = Path(value)
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Report must contain a JSON object: {path}")
    return data


def _flatten_numeric(value: Any, prefix: str = "") -> Dict[str, float]:
    out: Dict[str, float] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_numeric(child, name))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[prefix] = float(value)
    return out


def _issue_keys(report: Dict[str, Any]) -> set[str]:
    values = report.get("issues") or report.get("findings") or report.get("errors") or []
    result: set[str] = set()
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict):
                key = item.get("id") or item.get("fingerprint") or item.get("message") or item.get("title")
                result.add(str(key or json.dumps(item, sort_keys=True, default=str)))
            else:
                result.add(str(item))
    return result


def compare_debug_reports(baseline: str | Path | Dict[str, Any], current: str | Path | Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compare reports conservatively: new issues regress, removed issues improve.

    Numeric keys ending in *_errors, *_failures, *_warnings, or *_count are treated
    as lower-is-better. Keys ending in *_score, *_coverage, or *_passed are
    higher-is-better. Unknown numeric metrics are reported unchanged/changed but
    not classified as regressions to avoid guessing semantics.
    """
    base = _load_report(baseline)
    cur = _load_report(current)
    regressions: List[Dict[str, Any]] = []
    improvements: List[Dict[str, Any]] = []
    unchanged: List[Dict[str, Any]] = []

    old_issues, new_issues = _issue_keys(base), _issue_keys(cur)
    regressions.extend({"type": "new_issue", "key": key} for key in sorted(new_issues - old_issues))
    improvements.extend({"type": "resolved_issue", "key": key} for key in sorted(old_issues - new_issues))
    unchanged.extend({"type": "existing_issue", "key": key} for key in sorted(old_issues & new_issues))

    old_num, new_num = _flatten_numeric(base), _flatten_numeric(cur)
    for key in sorted(old_num.keys() & new_num.keys()):
        before, after = old_num[key], new_num[key]
        if before == after:
            continue
        lowered_good = key.lower().endswith(("errors", "error_count", "failures", "failure_count", "warnings", "warning_count"))
        raised_good = key.lower().endswith(("score", "coverage", "passed", "pass_count"))
        item = {"type": "metric", "metric": key, "before": before, "after": after}
        if lowered_good:
            (improvements if after < before else regressions).append(item)
        elif raised_good:
            (improvements if after > before else regressions).append(item)
        else:
            item["classification"] = "changed_unclassified"
            unchanged.append(item)
    return regressions, improvements, unchanged


def create_regression_report(
    *, baseline_debug: str | None, current_debug: str | None,
    baseline_test: str | None = None, current_test: str | None = None,
    restore_point_id: str | None = None,
    regressions: Iterable[Dict[str, Any]] = (), improvements: Iterable[Dict[str, Any]] = (),
    unchanged: Iterable[Dict[str, Any]] = (),
) -> str:
    init_database()
    report_id = str(uuid.uuid4())
    regs, imps, same = list(regressions), list(improvements), list(unchanged)
    status = "regressed" if regs else ("improved" if imps else "unchanged")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO regression_reports
               (id, baseline_ref, current_ref, status, regressions_json, improvements_json, unchanged_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_id, baseline_debug or baseline_test, current_debug or current_test, status,
             json.dumps(regs), json.dumps(imps), json.dumps(same), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    return report_id
