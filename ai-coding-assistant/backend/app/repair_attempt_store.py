"""Persistence for bounded repair attempts."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.database import get_db


def failure_signature(validation: Dict[str, Any]) -> str:
    blob = json.dumps(validation, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def store_repair_attempt(
    *, issue_id: str, cycle_id: str | None, attempt_no: int, model: str,
    diagnosis: str, changes: List[Dict[str, Any]], validation_plan: List[Dict[str, Any]],
    validation_result: Dict[str, Any], quality_score: float | None = None,
) -> Dict[str, Any]:
    record_id = str(uuid.uuid4())
    signature = failure_signature(validation_result) if not validation_result.get("passed") else ""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO repair_attempts
               (id, cycle_id, issue_id, attempt_no, model, diagnosis, patch_json,
                validation_plan_json, validation_result_json, failure_signature,
                quality_score, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, cycle_id, issue_id, attempt_no, model, diagnosis,
             json.dumps(changes), json.dumps(validation_plan), json.dumps(validation_result),
             signature, quality_score, now),
        )
        conn.commit()
    return {"id": record_id, "failure_signature": signature}


def get_repair_attempts(issue_id: str) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM repair_attempts WHERE issue_id=? ORDER BY attempt_no ASC", (issue_id,)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        for key in ("patch_json", "validation_plan_json", "validation_result_json"):
            try:
                item[key] = json.loads(item.get(key) or "null")
            except Exception:
                pass
        output.append(item)
    return output


def update_repair_attempt_result(record_id: str, validation_result: Dict[str, Any], quality_score: float | None = None) -> Dict[str, Any]:
    signature = failure_signature(validation_result) if not validation_result.get("passed") else ""
    with get_db() as conn:
        conn.execute(
            "UPDATE repair_attempts SET validation_result_json = ?, failure_signature = ?, quality_score = ? WHERE id = ?",
            (json.dumps(validation_result), signature, quality_score, record_id),
        )
        conn.commit()
    return {"id": record_id, "failure_signature": signature, "quality_score": quality_score}
