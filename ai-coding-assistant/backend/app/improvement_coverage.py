"""Coverage report ingestion and deterministic coverage delta calculation."""
from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict

from app.config import settings
from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pct(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).strip().rstrip("%"))
    except Exception:
        return None
    if 0 <= number <= 1:
        number *= 100.0
    return round(max(0.0, min(100.0, number)), 3)


def normalize_coverage_report(report: Any, report_format: str = "auto") -> Dict[str, Any]:
    fmt = str(report_format or "auto").lower()
    if isinstance(report, str):
        size = len(report.encode("utf-8"))
    else:
        try:
            size = len(json.dumps(report, ensure_ascii=False, default=str).encode("utf-8"))
        except Exception:
            size = int(settings.IMPROVEMENT_COVERAGE_MAX_REPORT_BYTES) + 1
    if size > int(settings.IMPROVEMENT_COVERAGE_MAX_REPORT_BYTES):
        raise ValueError("Coverage report exceeds configured size limit")
    data: Any = report
    if isinstance(report, str):
        text = report.strip()
        if fmt in {"xml", "cobertura"} or (fmt == "auto" and text.startswith("<")):
            root = ET.fromstring(text)
            return {
                "format": "cobertura",
                "line_coverage": _pct(root.attrib.get("line-rate")),
                "branch_coverage": _pct(root.attrib.get("branch-rate")),
                "lines_valid": int(float(root.attrib.get("lines-valid", 0) or 0)),
                "lines_covered": int(float(root.attrib.get("lines-covered", 0) or 0)),
            }
        try:
            data = json.loads(text)
        except Exception as exc:
            raise ValueError("Coverage report must be coverage.py JSON, generic JSON, or Cobertura XML") from exc
    if not isinstance(data, dict):
        raise ValueError("Coverage report must be an object or supported report string")
    totals = data.get("totals") if isinstance(data.get("totals"), dict) else data
    line = _pct(totals.get("percent_covered") if totals.get("percent_covered") is not None else totals.get("line_coverage"))
    branch = _pct(totals.get("percent_branches_covered") if totals.get("percent_branches_covered") is not None else totals.get("branch_coverage"))
    if line is None and totals.get("covered_lines") is not None and totals.get("num_statements"):
        line = _pct(float(totals.get("covered_lines")) / float(totals.get("num_statements")))
    result = {
        "format": "coverage.py-json" if "totals" in data else "generic-json",
        "line_coverage": line,
        "branch_coverage": branch,
        "num_statements": totals.get("num_statements"),
        "missing_lines": totals.get("missing_lines"),
        "num_branches": totals.get("num_branches"),
        "missing_branches": totals.get("missing_branches"),
    }
    if line is None and branch is None:
        raise ValueError("Coverage report did not contain recognizable coverage totals")
    return result


def store_coverage_report(*, project_name: str, phase: str, report: Any, report_format: str = "auto", cycle_id: str | None = None) -> Dict[str, Any]:
    init_database()
    normalized = normalize_coverage_report(report, report_format)
    report_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_coverage_reports
               (id, project_name, cycle_id, phase, format, line_coverage, branch_coverage, normalized_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_id, project_name, cycle_id, phase, normalized.get("format"), normalized.get("line_coverage"), normalized.get("branch_coverage"), json.dumps(normalized, ensure_ascii=False), now),
        )
        conn.commit()
    return {"id": report_id, "project_name": project_name, "cycle_id": cycle_id, "phase": phase, "created_at": now, **normalized}


def list_coverage_reports(project_name: str, *, cycle_id: str | None = None, limit: int = 50) -> list[Dict[str, Any]]:
    init_database()
    query = "SELECT * FROM improvement_coverage_reports WHERE project_name = ?"
    args: list[Any] = [project_name]
    if cycle_id:
        query += " AND cycle_id = ?"
        args.append(cycle_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    with get_db() as conn:
        rows = conn.execute(query, tuple(args)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["normalized"] = json.loads(item.pop("normalized_json") or "{}")
        except Exception:
            item["normalized"] = {}
        output.append(item)
    return output


def coverage_delta(project_name: str, *, cycle_id: str | None = None) -> Dict[str, Any]:
    rows = list_coverage_reports(project_name, cycle_id=cycle_id, limit=100)
    if cycle_id:
        baseline = next((row for row in reversed(rows) if row.get("phase") in {"baseline", "pre_apply"}), None)
        current = next((row for row in rows if row.get("phase") in {"post_apply", "current", "final"}), None)
    else:
        current = rows[0] if rows else None
        baseline = rows[1] if len(rows) > 1 else None
    def diff(key: str) -> float | None:
        if not baseline or not current or baseline.get(key) is None or current.get(key) is None:
            return None
        return round(float(current[key]) - float(baseline[key]), 3)
    return {
        "project_name": project_name,
        "cycle_id": cycle_id,
        "baseline": baseline,
        "current": current,
        "line_delta": diff("line_coverage"),
        "branch_delta": diff("branch_coverage"),
        "comparable": bool(baseline and current),
    }
