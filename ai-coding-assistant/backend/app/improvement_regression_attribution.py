"""Cross-cycle deterministic regression attribution for measured improvement outcomes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_regression_attribution(*, cycle_id: str, project_name: str, candidate_id: str | None, issue_id: str | None, outcome_id: str | None, baseline: Dict[str, Any] | None, final: Dict[str, Any] | None, changed_files: list[str] | None = None, apply_status: str = "unknown") -> Dict[str, Any]:
    init_database()
    before = (baseline or {}).get("dimensions") or {}
    after = (final or {}).get("dimensions") or {}
    deltas: Dict[str, float] = {}
    for key in sorted(set(before) | set(after)):
        if key in before and key in after:
            deltas[key] = round(float(after[key]) - float(before[key]), 3)
    regressions = {key: value for key, value in deltas.items() if value < 0}
    improvements = {key: value for key, value in deltas.items() if value > 0}
    failure_class = None
    if str(apply_status).startswith("rolled_back_health"):
        failure_class = "health_regression"
    elif str(apply_status).startswith("rolled_back"):
        failure_class = "rollback"
    elif regressions:
        failure_class = "dimension_regression"
    confidence = "high" if regressions and changed_files else ("medium" if regressions else "none")
    record_id = str(uuid.uuid4())
    now = _now()
    details = {"apply_status": apply_status, "improvements": improvements}
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_regression_attributions
               (id, cycle_id, candidate_id, issue_id, outcome_id, project_name, failure_class,
                dimension_deltas_json, regressed_dimensions_json, changed_files_json, confidence, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, cycle_id, candidate_id, issue_id, outcome_id, project_name, failure_class,
             json.dumps(deltas), json.dumps(regressions), json.dumps(changed_files or []), confidence, json.dumps(details), now),
        )
        conn.commit()
    return {"id": record_id, "cycle_id": cycle_id, "project_name": project_name, "failure_class": failure_class, "dimension_deltas": deltas, "regressed_dimensions": regressions, "changed_files": changed_files or [], "confidence": confidence, "details": details, "created_at": now}


def list_regression_attributions(project_name: str, *, limit: int = 100) -> list[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM improvement_regression_attributions WHERE project_name = ? ORDER BY created_at DESC LIMIT ?",
            (project_name, max(1, min(int(limit), 500))),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        for raw, clean, default in (("dimension_deltas_json", "dimension_deltas", {}), ("regressed_dimensions_json", "regressed_dimensions", {}), ("changed_files_json", "changed_files", []), ("details_json", "details", {})):
            try:
                item[clean] = json.loads(item.pop(raw) or json.dumps(default))
            except Exception:
                item[clean] = default
        output.append(item)
    return output
