"""Deterministic repeated-candidate suppression for improvement cycles."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable

from app.database import get_db, init_database

_ATTEMPTED_STATUSES = {
    "selected", "experimenting", "experiment_verified", "verified", "validation_failed",
    "budget_exceeded", "applied", "rolled_back", "discarded", "governance_blocked",
}


def candidate_fingerprint(candidate: Dict[str, Any]) -> str:
    finding = (candidate.get("evidence") or {}).get("health_finding") or {}
    payload = {
        "strategy_key": str(candidate.get("strategy_key") or ""),
        "category": str(finding.get("category") or ""),
        "code": str(finding.get("code") or ""),
        "risk": str(candidate.get("risk") or "medium"),
        "files": sorted(str(v).replace("\\", "/") for v in (candidate.get("likely_files") or [])),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def repeat_history(project_name: str, fingerprint: str, *, limit: int = 50) -> list[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.id, c.cycle_id, c.status, c.problem, c.updated_at, o.apply_status, o.score_delta
               FROM improvement_candidates c
               JOIN improvement_cycles y ON y.id = c.cycle_id
               LEFT JOIN improvement_outcomes o ON o.candidate_id = c.id
               WHERE y.project_name = ? AND c.candidate_fingerprint = ?
               ORDER BY COALESCE(c.updated_at, c.created_at) DESC LIMIT ?""",
            (project_name, fingerprint, max(1, min(int(limit), 500))),
        ).fetchall()
    return [dict(row) for row in rows]


def apply_repeat_suppression(
    project_name: str,
    candidates: Iterable[Dict[str, Any]],
    *,
    enabled: bool = True,
    repeat_limit: int = 2,
    history_limit: int = 50,
) -> list[Dict[str, Any]]:
    output: list[Dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        fingerprint = str(item.get("candidate_fingerprint") or candidate_fingerprint(item))
        history = repeat_history(project_name, fingerprint, limit=history_limit) if enabled else []
        attempted = [row for row in history if str(row.get("status") or "") in _ATTEMPTED_STATUSES]
        repeat_count = len(attempted)
        suppressed = bool(enabled and repeat_count >= max(1, int(repeat_limit)))
        reason = None
        if suppressed:
            last = attempted[0] if attempted else {}
            reason = f"repeated_candidate_limit:{repeat_count};last_status={last.get('status') or 'unknown'}"
        item.update({
            "candidate_fingerprint": fingerprint,
            "repeat_count": repeat_count,
            "suppressed": suppressed,
            "suppression_reason": reason,
        })
        output.append(item)
    output.sort(key=lambda item: (bool(item.get("suppressed")), -float(item.get("priority_score") or 0.0)))
    return output
